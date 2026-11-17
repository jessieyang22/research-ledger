# folder_policy: write-path and import gate

## What the module does
`as_of/folder_policy.py` is a static gate. It reads file paths and source text and returns `Finding` records. It never imports or runs the code it checks, and it makes no network calls. It runs three checks: every write path must resolve inside an allowed root (symlinks are followed); each module's imports must avoid forbidden roots, allow only numpy and pandas as third-party packages, and import at most one as_of module besides `as_of.core`; and `check_tree` applies both checks to every `.py` file under a folder.

## API
- `check_write_paths(paths, allowed_root)`: one Finding per path.
- `check_imports(source_text, module_name)`: PASS if all rules hold, otherwise FAIL findings. Syntax errors become FAIL findings, not exceptions.
- `check_tree(root)`: skips the top-level `tests/` folder and tool caches. Returns only FAIL findings plus one summary line.

Check IDs: `folder_policy.write_path`, `.forbidden_root`, `.third_party`, `.as_of_imports`, `.syntax`, `.tree`.

Example (run from the repo root; output verified):
```python
from as_of.folder_policy import check_write_paths, check_imports, check_tree

root = "as_of"  # relative to the repo root
for f in check_write_paths(["out/SYN_run.csv", "../SYN_x.csv"], root):
    print(f.status.name, f.subject)
for f in check_imports("import requests\n", "as_of.SYN_bad"):
    print(f.status.name, f.message)
print(check_tree(root)[-1].message)
```
Output:
```
PASS out/SYN_run.csv
FAIL ../SYN_x.csv
FAIL line 1: imports forbidden root 'requests'
52 python files checked, 0 failing findings
```
The file count in the last line changes as files are added.

## Known limits
- Static only: dynamic imports (`importlib`, `__import__`) and code built at runtime are not seen.
- The stdlib test uses `importlib.util.find_spec` on the installed interpreter, so an unusual install can misclassify a module name.
- `tests/` is excluded only at the package top level; nested folders with that name are checked.
- The write-path check looks at the resolved path string. It does not verify what a program actually writes.
- The forbidden roots and allowed third-party list come from `as_of.core` and are not reviewed here.
- Python 3.9 syntax only: the checker parses with `ast`, so newer syntax in checked files becomes a syntax FAIL.
