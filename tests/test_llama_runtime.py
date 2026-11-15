import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from llama_runtime import DiskCacheDisabled, import_llama, install_diskcache_guard

ROOT = Path(__file__).resolve().parents[1]


class DiskCacheGuardTests(unittest.TestCase):
    def test_guard_satisfies_the_import_but_refuses_every_cache(self):
        with patch.dict(sys.modules):
            sys.modules.pop("diskcache", None)
            install_diskcache_guard()
            import diskcache

            self.assertTrue(diskcache.__sonara_disabled__)
            for name in ("Cache", "FanoutCache", "Deque", "Index"):
                with self.subTest(name=name), self.assertRaisesRegex(DiskCacheDisabled, "PYSEC-2026-2447"):
                    getattr(diskcache, name)("/tmp/attacker-controlled")

    def test_guard_replaces_a_real_diskcache_already_imported(self):
        real = types.ModuleType("diskcache")
        real.Cache = object
        with patch.dict(sys.modules, {"diskcache": real}):
            install_diskcache_guard()
            self.assertIsNot(sys.modules["diskcache"], real)
            guarded = sys.modules["diskcache"]
            install_diskcache_guard()  # idempotent
            self.assertIs(sys.modules["diskcache"], guarded)

    def test_llama_cpp_imports_without_diskcache_installed(self):
        # Stands in for llama_cpp/llama_cache.py, which imports diskcache at load.
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "llama_cpp"
            package.mkdir()
            (package / "__init__.py").write_text(textwrap.dedent("""
                import diskcache

                class Llama:
                    pass

                class LlamaDiskCache:
                    def __init__(self, cache_dir):
                        self.cache = diskcache.Cache(cache_dir)
            """), encoding="utf-8")
            with patch.dict(sys.modules), patch.object(sys, "path", [directory, *sys.path]):
                for name in ("llama_cpp", "diskcache"):
                    sys.modules.pop(name, None)
                llama = import_llama()
                self.assertEqual(llama.__name__, "Llama")
                with self.assertRaises(DiskCacheDisabled):
                    sys.modules["llama_cpp"].LlamaDiskCache("cache")


class DependencyPinTests(unittest.TestCase):
    """diskcache must stay out of every install path Sonara documents."""

    def _pins(self, relative):
        names = set()
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-r"):
                names.add(line.split("==", 1)[0].casefold())
        return names

    def test_llama_cpp_python_is_only_in_no_deps_files(self):
        for resolved in ("requirements.txt", "requirements-llm.txt", "packaging/requirements-runtime.txt"):
            with self.subTest(file=resolved):
                self.assertNotIn("llama-cpp-python", self._pins(resolved))
                self.assertNotIn("diskcache", self._pins(resolved))
        for no_deps in ("requirements-llm-nodeps.txt", "packaging/requirements-runtime-nodeps.txt"):
            with self.subTest(file=no_deps):
                self.assertEqual(self._pins(no_deps), {"llama-cpp-python"})

    def test_llama_cpp_python_runtime_dependencies_are_pinned_instead(self):
        expected = {"jinja2", "markupsafe", "typing-extensions", "numpy"}
        self.assertLessEqual(expected, self._pins("packaging/requirements-runtime.txt"))
        self.assertLessEqual(expected - {"numpy"}, self._pins("requirements-llm.txt"))
        self.assertIn("numpy", self._pins("requirements.txt"))


if __name__ == "__main__":
    unittest.main()
