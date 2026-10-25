# Windows PowerShell launcher encoding fix

Root cause: the launcher was stored as UTF-8 without a BOM while containing an em dash. Windows PowerShell 5.1 can decode that byte sequence using the active ANSI code page, which may turn a byte inside the em dash into a quote-like character and report an unterminated string later in the file.

Fix: make `run-m-windows.ps1` ASCII-only and add a regression test to enforce it. This avoids changing Python, database settings, `.env`, or application data.
