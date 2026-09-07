# Running static checks

The reference lint environment is Linux with Python 3.11.16 and pre-commit
4.6.2. Hook versions and the Node runtime are specified in
`.pre-commit-config.yaml`. Use the .NET 8 SDK for the existing C# formatting
hook, and install Git, GCC and `xmllint` for the separate workflow checks.

Keep the virtual environment and logs outside the source checkout. Run the
gitignore check before installing hooks or creating generated files:

```sh
bash misc/scripts/gitignore_check.sh
python3.11 -m venv ../redot-lint-venv
../redot-lint-venv/bin/python -m pip install pre-commit==4.6.2
../redot-lint-venv/bin/python -m pre_commit install
```

From the repository root, run the automatic suite with:

```sh
../redot-lint-venv/bin/python -m pre_commit run --all-files --show-diff-on-failure
```

Hooks may modify files. Inspect the changes, then repeat the command to check
that it succeeds without further modifications. The manual Clang-Tidy stage
is not part of this command.

For an individual change, select its files or a verified ancestor range:

```sh
../redot-lint-venv/bin/python -m pre_commit run --files path/to/changed_file.py
../redot-lint-venv/bin/python -m pre_commit run --from-ref BASE_SHA --to-ref HEAD
```

The range selects filenames; hooks examine the current checkout. The checkout
must match the ending commit. CI's `ci_lint.py` validates event endpoints and
uses all files when no reliable base exists or lint inputs change.

Run the CI helper regression tests with:

```sh
../redot-lint-venv/bin/python tests/python_build/test_ci_lint.py
```

The portable helper tests also run on Windows using the virtual environment's
`Scripts/python.exe`. POSIX-only filename fixtures run on Linux. The full Linux
suite is not claimed to be portable to an unconfigured PowerShell environment.

The workflow also runs XML schema and C-interface checks outside pre-commit.
See `.github/workflows/static_checks.yml` for those commands.

Action revisions, Python, pre-commit, Node and direct hook dependencies are
pinned. Transitive package dependencies and runner images are not completely
locked. When updating pins, validate a cold-cache run and review changes in
lint output before reusing a formatter baseline.
