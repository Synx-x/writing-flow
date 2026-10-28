# Security policy

Report security defects to the repository owner through a private channel.
Include the affected version, the steps to reproduce the issue, and any
available impact details. Do not include secrets in a public report.

The hooks read event data and project files. They write state only under the
configured writing-flow state directory. Set `WRITING_FLOW_STATE_DIR` to move
that state for a test or isolated run.
