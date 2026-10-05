import copy
import importlib
from pathlib import Path
import unittest

from dev.python.locked_env import COLMAP_SHA, LOCK_SHA, PARENT_DIGEST, PYTHON_SHA


class DerivedContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.checker = importlib.import_module("scripts.check_dev_python_contract")
        except ModuleNotFoundError:
            self.checker = None
        self.assertIsNotNone(self.checker, "schema2 checker is missing")
        from scripts.check_dev_contract import expected_native_contract

        self.native = expected_native_contract(COLMAP_SHA)

    def contract(self):
        runtime = {"interpreter": {"sha256": PYTHON_SHA, "version": "3.14.7"}}
        return self.checker.make_contract(self.native, runtime, "b" * 64)

    def test_schema2_preserves_exact_native_projection(self):
        contract = self.contract()
        self.assertEqual(self.checker.native_projection(contract), self.native)
        self.assertEqual(contract["native_parent_digest"], PARENT_DIGEST)
        self.assertEqual(contract["environment_lock_sha256"], LOCK_SHA)
        self.assertEqual(contract["python"]["prefix"], "/opt/colmap-python")

    def test_extra_fields_boolean_schema_and_parent_confusion_rejected(self):
        for mutate in (
            lambda c: c.update(schema_version=True),
            lambda c: c.update(unexpected=True),
            lambda c: c.update(gpu_execution_validated=0),
            lambda c: c.update(native_parent_digest="sha256:" + "a" * 64),
            lambda c: c["python"].update(executable="/usr/bin/python3"),
        ):
            contract = copy.deepcopy(self.contract())
            mutate(contract)
            with self.assertRaises(ValueError):
                self.checker.validate_contract(contract, "b" * 64)

    def test_manifest_hash_and_native_binary_changes_rejected(self):
        with self.assertRaises(ValueError):
            self.checker.validate_contract(self.contract(), "c" * 64)
        contract = self.contract()
        contract["binary_sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            self.checker.validate_contract(contract, "b" * 64)
