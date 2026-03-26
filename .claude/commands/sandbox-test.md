Run tests in the sandbox container.

Execute: `sandbox/sandbox.sh test $ARGUMENTS`

If no arguments provided, run unit tests. Accepted arguments:
- `unit` — run all unit tests
- `integration` — run all integration tests
- A specific path like `tests/unit/test_foo.py` or `tests/unit/test_foo.py::test_name`

After tests complete, report the results summary (passed, failed, errors).
