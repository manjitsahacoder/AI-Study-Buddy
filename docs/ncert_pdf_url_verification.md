# NCERT PDF URL verification

Verification date: 2026-08-15

Source: [NCERT Textbooks PDF portal](https://ncert.nic.in/textbook.php).

The Class 9 English-language books below were checked directly on the official
NCERT host. Every registered URL returned an HTTP success response with
`application/pdf` and a `%PDF-` signature. Titles were confirmed from each
chapter PDF's extracted opening page. Whole-book placeholders remain unchanged
because the portal's complete-book download may be a ZIP archive.

## Science — *Exploration* (13 of 13 registered)

| No. | Chapter | PDF |
| --- | --- | --- |
| 1 | Exploration: Entering the World of Secondary Science | `iesc101.pdf` |
| 2 | Cell: The Building Block of Life | `iesc102.pdf` |
| 3 | Tissues in Action | `iesc103.pdf` |
| 4 | Describing Motion Around Us | `iesc104.pdf` |
| 5 | Exploring Mixtures and their Separation | `iesc105.pdf` |
| 6 | How Forces Affect Motion | `iesc106.pdf` |
| 7 | Work, Energy, and Simple Machines | `iesc107.pdf` |
| 8 | Journey Inside the Atom | `iesc108.pdf` |
| 9 | Atomic Foundations of Matter | `iesc109.pdf` |
| 10 | Sound Waves: Characteristics and Applications | `iesc110.pdf` |
| 11 | Reproduction: How Life Continues | `iesc111.pdf` |
| 12 | Patterns in Life: Diversity and Classification | `iesc112.pdf` |
| 13 | Earth as a System: Energy, Matter, and Life | `iesc113.pdf` |

## Mathematics — *Ganita Manjari* (8 of 8 registered)

| No. | Chapter | PDF |
| --- | --- | --- |
| 1 | Orienting Yourself: The Use of Coordinates | `iemh101.pdf` |
| 2 | Introduction to Linear Polynomials | `iemh102.pdf` |
| 3 | The World of Numbers | `iemh103.pdf` |
| 4 | Exploring Algebraic Identities | `iemh104.pdf` |
| 5 | I’m Up and Down, and Round and Round | `iemh105.pdf` |
| 6 | Measuring Space: Perimeter and Area | `iemh106.pdf` |
| 7 | The Mathematics of Maybe: Introduction to Probability | `iemh107.pdf` |
| 8 | Predicting What Comes Next: Exploring Sequences and Progressions | `iemh108.pdf` |

## English — *Kaveri* (8 of 8 registered)

| No. | Chapter | PDF |
| --- | --- | --- |
| 1 | How I Taught My Grandmother to Read | `iebe101.pdf` |
| 2 | The Pot Maker | `iebe102.pdf` |
| 3 | Winds of Change | `iebe103.pdf` |
| 4 | Vitamin-M | `iebe104.pdf` |
| 5 | The World of Limitless Possibilities | `iebe105.pdf` |
| 6 | Twin Melodies | `iebe106.pdf` |
| 7 | Carrier of Words | `iebe107.pdf` |
| 8 | Follow That Dream | `iebe108.pdf` |

## Social Science — *Understanding Society: India and Beyond Part-I* (9 of 9 registered)

| No. | Chapter | PDF |
| --- | --- | --- |
| 1 | Understanding Social Science | `iest101.pdf` |
| 2 | Shaping of the Earth’s Surface | `iest102.pdf` |
| 3 | Atmosphere and Climate | `iest103.pdf` |
| 4 | Early Humans and Beginning of Civilisation | `iest104.pdf` |
| 5 | State and Society up to 1000 CE | `iest105.pdf` |
| 6 | Democracy | `iest106.pdf` |
| 7 | Elections | `iest107.pdf` |
| 8 | Building Blocks in Economics: The Problem of Choice | `iest108.pdf` |
| 9 | The Price Puzzle: What Drives the Market | `iest109.pdf` |

All 38 mappings are currently supported. No verified Class 9 chapter URL is
intentionally left unsupported in these four priority subjects.

Run the manual verifier after any registry URL change:

```powershell
python scripts/verify_textbook_pdf_urls.py
```

The verifier is not part of normal tests. It reports class, subject, textbook,
chapter number/title, URL, HTTP status, MIME type, PDF signature, attempts, and
any failure reason; transient request errors receive limited retries.
