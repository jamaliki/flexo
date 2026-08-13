## Shell Safety

- In zsh commands and scripts, never use `path` as a variable or loop-variable
  name. In zsh, the special `path` array is tied to `PATH`, so assigning `path`
  overwrites the executable search path. Use names such as `file`, `relpath`, or
  `target_path` instead.
