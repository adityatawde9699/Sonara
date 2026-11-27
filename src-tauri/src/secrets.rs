//! Assistant API keys, kept by Rust so the webview never holds them.
//!
//! Each provider's key goes to the OS credential store (macOS Keychain,
//! Windows Credential Manager, or the freedesktop Secret Service on Linux).
//! When no store is available, as on a headless Linux session without a
//! Secret Service, the key is kept in memory for this run only. Rust adds the
//! key to each assistant request itself.

use serde::Serialize;
use std::collections::HashMap;
use std::sync::Mutex;

const SERVICE: &str = "com.sonara.reader.assistant";

/// Where a saved key lives.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum KeyStorage {
    /// The OS credential store; survives restarts.
    Keychain,
    /// Memory only, because no credential store was available.
    Session,
}

/// A credential store. The real one is the OS store; tests use fakes.
pub(crate) trait KeyBackend: Send + Sync {
    fn set(&self, provider: &str, key: &str) -> Result<(), String>;
    fn get(&self, provider: &str) -> Result<Option<String>, String>;
    fn delete(&self, provider: &str) -> Result<(), String>;
}

struct OsKeyring;

impl OsKeyring {
    fn entry(provider: &str) -> Result<keyring::Entry, String> {
        keyring::Entry::new(SERVICE, provider).map_err(|error| error.to_string())
    }
}

impl KeyBackend for OsKeyring {
    fn set(&self, provider: &str, key: &str) -> Result<(), String> {
        Self::entry(provider)?
            .set_password(key)
            .map_err(|error| error.to_string())
    }

    fn get(&self, provider: &str) -> Result<Option<String>, String> {
        match Self::entry(provider)?.get_password() {
            Ok(key) => Ok(Some(key)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(error.to_string()),
        }
    }

    fn delete(&self, provider: &str) -> Result<(), String> {
        match Self::entry(provider)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(error.to_string()),
        }
    }
}

pub(crate) struct ApiKeys {
    backend: Box<dyn KeyBackend>,
    /// Keys read or saved this run, so a request does not wait on the store;
    /// also the only copy of a `Session` key.
    known: Mutex<HashMap<String, (String, KeyStorage)>>,
}

impl Default for ApiKeys {
    fn default() -> Self {
        Self::with_backend(Box::new(OsKeyring))
    }
}

/// Provider names are Sonara's own ("openai", "gemini", …).
fn valid_provider(provider: &str) -> Result<(), String> {
    let ok = !provider.is_empty()
        && provider.len() <= 32
        && provider
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_');
    if ok {
        Ok(())
    } else {
        Err("Unknown assistant provider.".to_owned())
    }
}

impl ApiKeys {
    pub(crate) fn with_backend(backend: Box<dyn KeyBackend>) -> Self {
        Self {
            backend,
            known: Mutex::new(HashMap::new()),
        }
    }

    fn known(&self) -> std::sync::MutexGuard<'_, HashMap<String, (String, KeyStorage)>> {
        // A poisoned map only ever holds whole entries; keep using it.
        self.known
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
    }

    /// Save `key` for `provider`: in the credential store, else for this run.
    pub(crate) fn save(&self, provider: &str, key: &str) -> Result<KeyStorage, String> {
        valid_provider(provider)?;
        let key = key.trim();
        if key.is_empty() {
            return Err("The API key is empty.".to_owned());
        }
        if key.len() > 4096 {
            return Err("The API key is too long.".to_owned());
        }
        let storage = match self.backend.set(provider, key) {
            Ok(()) => KeyStorage::Keychain,
            Err(error) => {
                eprintln!("sonara: no credential store, keeping the key for this session: {error}");
                KeyStorage::Session
            }
        };
        self.known()
            .insert(provider.to_owned(), (key.to_owned(), storage));
        Ok(storage)
    }

    /// The key for `provider`, if one was saved.
    pub(crate) fn get(&self, provider: &str) -> Option<String> {
        self.lookup(provider).map(|(key, _)| key)
    }

    /// Where the key for `provider` is kept, if one was saved.
    pub(crate) fn status(&self, provider: &str) -> Option<KeyStorage> {
        self.lookup(provider).map(|(_, storage)| storage)
    }

    fn lookup(&self, provider: &str) -> Option<(String, KeyStorage)> {
        valid_provider(provider).ok()?;
        if let Some(found) = self.known().get(provider) {
            return Some(found.clone());
        }
        let key = self.backend.get(provider).ok().flatten()?;
        let found = (key, KeyStorage::Keychain);
        self.known().insert(provider.to_owned(), found.clone());
        Some(found)
    }

    /// Forget the key for `provider` everywhere.
    pub(crate) fn clear(&self, provider: &str) -> Result<(), String> {
        valid_provider(provider)?;
        let stored = self.known().remove(provider).map(|(_, storage)| storage);
        match self.backend.delete(provider) {
            Ok(()) => Ok(()),
            // Nothing reached the store, so there is nothing to delete there.
            Err(_) if stored == Some(KeyStorage::Session) => Ok(()),
            Err(error) => Err(format!(
                "Could not remove the key from the system keychain: {error}"
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct FakeStore(Mutex<HashMap<String, String>>);

    impl KeyBackend for FakeStore {
        fn set(&self, provider: &str, key: &str) -> Result<(), String> {
            self.0
                .lock()
                .unwrap()
                .insert(provider.to_owned(), key.to_owned());
            Ok(())
        }
        fn get(&self, provider: &str) -> Result<Option<String>, String> {
            Ok(self.0.lock().unwrap().get(provider).cloned())
        }
        fn delete(&self, provider: &str) -> Result<(), String> {
            self.0.lock().unwrap().remove(provider);
            Ok(())
        }
    }

    /// No Secret Service, as on a headless Linux session.
    struct NoStore;

    impl KeyBackend for NoStore {
        fn set(&self, _: &str, _: &str) -> Result<(), String> {
            Err("no secret service".to_owned())
        }
        fn get(&self, _: &str) -> Result<Option<String>, String> {
            Err("no secret service".to_owned())
        }
        fn delete(&self, _: &str) -> Result<(), String> {
            Err("no secret service".to_owned())
        }
    }

    #[test]
    fn keys_go_to_the_credential_store_and_survive_a_restart() {
        let store = std::sync::Arc::new(FakeStore::default());
        struct Shared(std::sync::Arc<FakeStore>);
        impl KeyBackend for Shared {
            fn set(&self, p: &str, k: &str) -> Result<(), String> {
                self.0.set(p, k)
            }
            fn get(&self, p: &str) -> Result<Option<String>, String> {
                self.0.get(p)
            }
            fn delete(&self, p: &str) -> Result<(), String> {
                self.0.delete(p)
            }
        }
        let keys = ApiKeys::with_backend(Box::new(Shared(store.clone())));
        assert_eq!(
            keys.save("openai", "  sk-test  ").unwrap(),
            KeyStorage::Keychain
        );
        assert_eq!(keys.get("openai").as_deref(), Some("sk-test"));

        // A new run reads it back from the store.
        let restarted = ApiKeys::with_backend(Box::new(Shared(store.clone())));
        assert_eq!(restarted.status("openai"), Some(KeyStorage::Keychain));
        assert_eq!(restarted.get("openai").as_deref(), Some("sk-test"));
        assert_eq!(restarted.status("gemini"), None);

        restarted.clear("openai").unwrap();
        assert_eq!(restarted.get("openai"), None);
        assert!(store.0.lock().unwrap().is_empty());
    }

    #[test]
    fn without_a_credential_store_keys_last_for_the_session() {
        let keys = ApiKeys::with_backend(Box::new(NoStore));
        assert_eq!(keys.save("gemini", "g-key").unwrap(), KeyStorage::Session);
        assert_eq!(keys.status("gemini"), Some(KeyStorage::Session));
        assert_eq!(keys.get("gemini").as_deref(), Some("g-key"));
        keys.clear("gemini").unwrap();
        assert_eq!(keys.get("gemini"), None);
    }

    #[test]
    fn bad_input_is_refused() {
        let keys = ApiKeys::with_backend(Box::new(FakeStore::default()));
        assert!(keys.save("openai", "   ").is_err());
        assert!(keys.save("../x", "k").is_err());
        assert!(keys.save("openai", &"k".repeat(5000)).is_err());
        assert_eq!(keys.get("Open AI"), None);
    }
}
