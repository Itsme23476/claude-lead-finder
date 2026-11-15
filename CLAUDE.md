# Claude Lead Finder

This repo finds local business leads (name, address, rating, reviews, website, email, phone) for a niche and a city, using Decodo's Web Data API. The script is `find_leads.py`. It only reads public business pages.

## When the user asks for leads

Turn the request into one command and run it. Examples:

| The user says | Run |
| - | - |
| "Find roofers in Dallas" | `python3 find_leads.py roofers "Dallas, TX"` |
| "Plumbers in Phoenix and Tucson, 4 stars or more" | `python3 find_leads.py plumbers "Phoenix, AZ" "Tucson, AZ" --min-stars 4` |
| "Dentists in Austin with at least 50 reviews, only ones with an email" | `python3 find_leads.py dentists "Austin, TX" --min-reviews 50 --email-only` |
| "500 HVAC leads across Texas" | `python3 find_leads.py "hvac companies" "Houston, TX" "San Antonio, TX" "Dallas, TX" "Austin, TX" "Fort Worth, TX" --max 500` |
| "Electricians in Toronto" | `python3 find_leads.py electricians "Toronto, ON" --country Canada` |

- Always give the city with its state or region, like "Dallas, TX".
- For a big number of leads, pass many cities in one command. One city gives roughly 25 to 60 leads.
- Results go to `leads-<niche>.csv`. Running the same niche again adds to that file and skips businesses it already has, so a stopped run can just be started again.
- After a run, tell the user the totals the script prints: leads, how many have an email and a phone, and how much of the free plan it used.

If `.env` has no key, tell the user to copy `.env.example` to `.env` and paste their Decodo API key. Never print the key.

## Rules that keep each lead cheap (don't change these)

1. Websites come from Google's own map results. Don't add a separate search per business to find its website.
2. Read pages with `"proxy_pool": "standard"`. Use premium only when standard fails.
3. Read the contact page only when the homepage has no email.
4. Apply star and review filters before reading any website, so filtered businesses cost nothing.
5. Never follow ad links (`/aclk`). Skip directories and social sites.
6. Don't turn on JavaScript rendering (`headless`). It costs more and these sites don't need it.

## Scoring the leads (no extra requests)

Every website the script reads is saved in `pages/<domain>.md`. When the user asks to score or qualify leads:

1. Read the leads CSV and, for each lead, its file in `pages/`.
2. Add these columns: what they do (one line), fit score from 1 to 10 for the user's offer, the reason for the score, and a personal first line for a cold email based on their website.
3. Sort by score and save it as `scored-<niche>.csv`.

Ask the user what they sell first if they haven't said. Don't make API calls for this step.

## Owner names (optional, costs more)

If the user wants owner or manager names, use Decodo's `/map` endpoint on the lead's website to find the About or Team page, read it with `/scrape` (standard pool, Markdown), and add the name only if the page states it. Leave it blank otherwise, never guess. This costs a couple of extra requests per lead, so do it only for the top leads the user picks, and say so before running it.

## Without Claude

Everything above except scoring works without Claude. The user can run the same `python3 find_leads.py ...` commands in any terminal.

## Cold email

Remind the user to follow the cold email rules where they live (for example, an unsubscribe link and a business address in the US).
