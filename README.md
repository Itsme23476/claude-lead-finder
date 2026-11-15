# Claude Lead Finder

Type a niche and a city, and get a spreadsheet of local businesses from Google: name, address, rating, reviews, website, email and phone. Run it from Claude Code by just asking ("find roofers in Dallas"), or straight from your terminal.

It uses [Decodo's Web Data API](https://decodo.com/web-data-api), which has a free plan with up to 10,000 requests a month and no credit card. Every run prints how much of the free plan it used.

## Setup

```bash
git clone https://github.com/Itsme23476/claude-lead-finder.git
cd claude-lead-finder
cp .env.example .env
```

Paste your Decodo API key into `.env`. It needs Python 3.9 or newer and nothing else to install.

## Use it in Claude Code

Open the folder in Claude Code and ask in plain words:

- "Find roofers in Dallas"
- "Plumbers in Phoenix and Tucson with at least 4 stars and 20 reviews"
- "Score these leads for my website design offer and write a first line for each"

`CLAUDE.md` tells Claude how to run the script and how to score the leads without making new requests.

## Use it without Claude

```bash
python3 find_leads.py roofers "Dallas, TX"
python3 find_leads.py plumbers "Phoenix, AZ" "Tucson, AZ" --min-stars 4 --min-reviews 20
python3 find_leads.py dentists "Austin, TX" --email-only --max 200
```

| Option | What it does |
| - | - |
| `--min-stars 4` | Only businesses rated 4 stars or more |
| `--min-reviews 20` | Only businesses with at least 20 Google reviews |
| `--email-only` | Only keep leads with an email |
| `--max 500` | Stop at this many leads |
| `--country Canada` | Search Google from another country |

Results go to `leads-<niche>.csv`. Run the same niche again with new cities and it adds to the file, skipping businesses it already has.

## How it keeps each lead cheap

- Websites come from Google's own map results, so there's no extra search per business.
- Each website is read once, as Markdown, on the standard proxy pool. Premium is only used when a site blocks it.
- The contact page is read only when the homepage has no email.
- Star and review filters run before any website is read.
- It stops searching a city once new searches stop finding new businesses.

In testing, one city gave 26 to 57 leads. Roofers in Dallas came to about 2.2 requests per lead.

## What you get, honestly

- Every lead has a website, and most have a phone number.
- About 40 to 50% have an email. These are business inboxes like info@ or office@, not personal emails.
- Only public business pages are read. If you email these leads, follow the cold email rules where you live.
