# NCERT PDF URL verification

Verification date: 2026-08-10

Source: [NCERT Textbooks PDF portal](https://ncert.nic.in/textbook.php)

The prioritized Class 9 English-language catalog entries currently expose each
book as multiple chapter PDFs. The portal's "Download complete book" link is a
ZIP archive, not a whole-book PDF. Sprint 2 Milestone 3 intentionally keeps the
registry placeholders rather than representing one chapter as an entire book or
passing a ZIP URL to the PDF-only cache service.

| Subject | Current NCERT catalog title | Verified chapter response | Complete-book response | Registry result |
| --- | --- | --- | --- | --- |
| Science | Exploration | `iesc101.pdf`: HTTP 206, `application/pdf`, `%PDF-` | `iesc1dd.zip`: HTTP 200, `application/zip` | Placeholder retained |
| Mathematics | Ganita Manjari | `iemh101.pdf`: HTTP 206, `application/pdf`, `%PDF-` | `iemh1dd.zip`: HTTP 200, `application/zip` | Placeholder retained |
| English | Kaveri | `iebe101.pdf`: HTTP 206, `application/pdf`, `%PDF-` | `iebe1dd.zip`: HTTP 200, `application/zip` | Placeholder retained |
| Social Science | Understanding Society India and Beyond Part-I | `iest101.pdf`: HTTP 206, `application/pdf`, `%PDF-` | `iest1dd.zip`: HTTP 200, `application/zip` | Placeholder retained |

No verified whole-book PDF URL was found for this subset, so no real URL was
added to `data/ncert_textbooks.json`. The text extraction service will work with
any future registry entry that passes the existing Milestone 2 HTTP/PDF
validation. The manual verifier can be rerun after registry changes:

```powershell
python scripts/verify_textbook_pdf_urls.py
```

The verifier is not part of the normal test suite and performs a ranged GET to
check status, final official host, and the `%PDF-` signature.
