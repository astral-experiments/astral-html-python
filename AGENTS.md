* This project is automated. Open a pull request for each improvement, review the diff, and fix any findings. After review, you may merge the PR into `main` without additional permission, even before PR CI finishes. Verify CI on the resulting `main` commit. If CI fails, promptly fix the cause in a follow-up PR.
* The Readme is concise and only contains deep information. Do not add random information there. Keep source-build instructions in the development guide so the quick start opens with Python usage.
* Consider if you need really new sections in the documentation, or if you can avoid it.
* When the reason for a fix or improvement isn't clear from the code, add or update a comment beside the relevant logic. Explain the constraint it satisfies or the failure it prevents.
* If we undo something previously done, document that, so we don't do it again.
* CI may only download actions, tools, and dependencies pinned by hash. Pin actions to full commit SHAs and verify downloaded artifacts against trusted, pinned digests before use.
