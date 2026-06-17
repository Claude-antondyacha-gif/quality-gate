# quality-gate
Marketing text quality checker — scores 0-100, blocks publish if &lt;60
# 🔍 Quality Gate

Marketing text quality checker for Ukrainian/Russian digital marketing content.

## Scoring (0–100, publish blocked if <60)

| Criterion | Target | Weight |
|-----------|--------|--------|
| Expert words | ≥ 15% | 25 pts |
| Water words | ≤ 10% | 25 pts |
| Sentence length | ~9 words | 25 pts |
| No clichés | 0 patterns | 25 pts |

## Usage

```bash
python3 quality_gate.py -t "Your text here"
python3 quality_gate.py -f mytext.txt
python3 quality_gate.py -f mytext.txt --json
```

## Requirements
Python 3.8+ · No external dependencies
