//! Keep each worker and every process it starts together, so they stop as
//! one and do not outlive Sonara.
//!
//! - Unix: the speech worker leads its own process group (set at spawn), and
//!   `stop_worker_tree` signals the whole group. Piper runs in that group.
//! - Windows: each worker is put in a Job Object with kill-on-close. Its
//!   children join the job automatically, terminating the job stops the whole
//!   tree, and when Sonara exits for any reason, including a crash, Windows
//!   closes the handle and kills what is left.
//! - Everywhere: workers get `SONARA_PARENT_WATCH=1`. The Python side
//!   (`parent_watch.py`) then exits, taking its process group with it, when
//!   its parent process is gone. On Unix this covers a crash or abort, where
//!   no Rust cleanup runs.
//!
//! A process could start children in the moment between spawn and joining
//! the job. Sonara's workers spend far longer than that importing Python
//! modules before they start Piper.

use std::process::{Child, Command};

pub(crate) const PARENT_WATCH_ENV: &str = "SONARA_PARENT_WATCH";

/// Variables a worker may inherit. Everything else, including credentials in
/// the user's shell environment, is cleared.
const BASE_ENV: &[&str] = &[
    "HOME",
    "LANG",
    "LC_ALL",
    "LD_LIBRARY_PATH",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "SONARA_CACHE_DIR",
    "SONARA_OCR_CACHE_DIR",
];

/// Added for the LLM worker, which may reach an HTTP provider through a proxy
/// or with a custom CA bundle.
const NETWORK_ENV: &[&str] = &[
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
];

/// A command with a cleared environment plus the variables workers need.
/// Callers still apply `configure_runtime_command` for PATH and tool paths.
pub(crate) fn worker_command(program: &std::path::Path, network: bool) -> Command {
    let mut command = Command::new(program);
    command.env_clear();
    let allowed = BASE_ENV
        .iter()
        .chain(if network { NETWORK_ENV } else { &[] });
    for name in allowed {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    command.env(PARENT_WATCH_ENV, "1");
    command
}

#[cfg(windows)]
mod job {
    use std::collections::HashMap;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use std::sync::{Mutex, OnceLock};
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// Job handles by worker process id. Stored as integers because raw
    /// handles are not `Send`.
    fn jobs() -> &'static Mutex<HashMap<u32, isize>> {
        static JOBS: OnceLock<Mutex<HashMap<u32, isize>>> = OnceLock::new();
        JOBS.get_or_init(|| Mutex::new(HashMap::new()))
    }

    pub(super) fn adopt(child: &Child) -> Result<(), String> {
        // SAFETY: plain Win32 calls on a handle this function owns, and on
        // the child's process handle, which stays valid while `child` lives.
        unsafe {
            let job: HANDLE = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return Err("Could not create a job object for the worker.".to_owned());
            }
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let configured = SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );
            if configured == 0
                || AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) == 0
            {
                CloseHandle(job);
                return Err("Could not place the worker in a job object.".to_owned());
            }
            if let Ok(mut jobs) = jobs().lock() {
                if let Some(previous) = jobs.insert(child.id(), job as isize) {
                    CloseHandle(previous as HANDLE);
                }
            }
        }
        Ok(())
    }

    pub(super) fn terminate(pid: u32) {
        if let Ok(jobs) = jobs().lock() {
            if let Some(job) = jobs.get(&pid) {
                // SAFETY: the handle is owned by the map and still open.
                unsafe {
                    TerminateJobObject(*job as HANDLE, 1);
                }
            }
        }
    }

    pub(super) fn release(pid: u32) {
        let job = jobs().lock().ok().and_then(|mut jobs| jobs.remove(&pid));
        if let Some(job) = job {
            // SAFETY: removed from the map, so this is the only owner.
            // Kill-on-close also stops anything the worker left behind.
            unsafe {
                CloseHandle(job as HANDLE);
            }
        }
    }
}

/// Put a freshly spawned worker under process-tree control. On Unix the
/// process group was already set at spawn, so there is nothing to do.
pub(crate) fn adopt(child: &Child) -> Result<(), String> {
    #[cfg(windows)]
    return job::adopt(child);
    #[cfg(not(windows))]
    {
        let _ = child;
        Ok(())
    }
}

/// Kill every process in the worker's tree (Windows; Unix uses the group).
pub(crate) fn terminate(pid: u32) {
    #[cfg(windows)]
    job::terminate(pid);
    #[cfg(not(windows))]
    let _ = pid;
}

/// Forget a worker that has exited, stopping anything it left running.
pub(crate) fn release(pid: u32) {
    #[cfg(windows)]
    job::release(pid);
    #[cfg(not(windows))]
    let _ = pid;
}

/// Stop a worker that has no process group to signal (the LLM worker):
/// kill it and anything it started, reap it, and forget its job.
pub(crate) fn kill_and_reap(child: &mut Child) {
    terminate(child.id());
    let _ = child.kill();
    let _ = child.wait();
    release(child.id());
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;

    fn env_of(command: &Command) -> Vec<(String, Option<String>)> {
        command
            .get_envs()
            .map(|(name, value)| {
                (
                    name.to_string_lossy().into_owned(),
                    value.map(|value| value.to_string_lossy().into_owned()),
                )
            })
            .collect()
    }

    #[test]
    fn workers_get_a_cleared_environment_with_the_parent_watch() {
        // Inherited only if allowed: a variable that is not on the list is
        // absent even when the parent has it (PATH always exists).
        let command = worker_command(std::path::Path::new("python"), false);
        let env = env_of(&command);
        assert!(env.contains(&(PARENT_WATCH_ENV.to_owned(), Some("1".to_owned()))));
        assert!(!env.iter().any(|(name, _)| name == "PATH"));
        assert!(env
            .iter()
            .all(|(name, _)| name == PARENT_WATCH_ENV || BASE_ENV.contains(&name.as_str())));
        assert!(command
            .get_envs()
            .all(|(name, _)| name != OsStr::new("HTTPS_PROXY")));
    }

    #[test]
    fn only_the_network_worker_may_inherit_proxy_settings() {
        let network = env_of(&worker_command(std::path::Path::new("python"), true));
        assert!(network.iter().all(|(name, _)| name == PARENT_WATCH_ENV
            || BASE_ENV.contains(&name.as_str())
            || NETWORK_ENV.contains(&name.as_str())));
    }
}
