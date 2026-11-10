# Google Business Profile review sync

Pulls **every** review on the Royaall Wool Google listing (Salkia, Howrah — 4.9★,
153 reviews) into Mongo, so the storefront can show all of them instead of the
5 the public Places API caps at. New reviews land automatically: the backend
re-syncs every 6 hours, and `POST /google-reviews/sync` forces one.

## Why this API and not the Places API

| | Places API (public) | Business Profile API (owner) |
|---|---|---|
| Reviews returned | 5, fixed | all of them |
| Needs | API key | OAuth as an account that manages the location |
| Cost | per request | free |
| Review photos | no | no |

Neither API returns the photos customers attach to a review — that data is only
on the public listing. Three reviews were captured with their photos and seeded
(`scripts/seed_google_reviews.py`); the sync preserves photos on any review that
already has them.

## One-time setup

1. **Request API access.** Fill Google's access form for the Business Profile
   APIs (search "Business Profile APIs get started"). Approval is manual and
   usually takes a few days. Use the Google account that owns the listing.
2. **Google Cloud project.** In the Cloud Console enable *My Business Account
   Management API* and *My Business Business Information API*, plus the legacy
   *Google My Business API* (that is the one that serves reviews).
3. **OAuth client.** Credentials → Create credentials → OAuth client ID →
   *Desktop app*. Note the client id and secret.
4. **Refresh token.** Run the OAuth consent flow once with scope
   `https://www.googleapis.com/auth/business.manage` and keep the
   `refresh_token` from the token response (`access_type=offline`).
5. **Account and location ids.**

   ```bash
   curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     https://mybusinessaccountmanagement.googleapis.com/v1/accounts
   curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     "https://mybusinessbusinessinformation.googleapis.com/v1/accounts/<ACCOUNT_ID>/locations?readMask=name,title"
   ```

   Use the numeric ids (the part after `accounts/` and `locations/`).

## Environment

Add to the backend `.env`:

```
GOOGLE_GBP_CLIENT_ID=
GOOGLE_GBP_CLIENT_SECRET=
GOOGLE_GBP_REFRESH_TOKEN=
GOOGLE_GBP_ACCOUNT_ID=
GOOGLE_GBP_LOCATION_ID=
```

Until these are set the sync stays quiet and the storefront serves whatever is
already in the `google_reviews` collection.

## Endpoints

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/google-reviews?limit=&offset=&with_photos=` | public | review feed, newest first |
| GET | `/google-reviews/summary` | public | count, average, star breakdown, last sync |
| POST | `/google-reviews/sync` | admin | force a pull from Google |

The storefront calls `/google-reviews` once and pages through the result six at
a time behind the "See more" button.
