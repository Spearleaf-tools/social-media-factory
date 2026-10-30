# Outside services: what they're for, what they cost, how to set them up

**You can start with nothing beyond Claude.** Writing posts, making carousels and cards, reviewing them
and saving a ready-to-post folder need no other account and cost nothing more. (Posting by hand still
needs your own social accounts.) The services below are only for the features that use them, so set up
a service only when you want one of its features.

This page is made from `smf/services.json`, the one place the prices live, so it always says the same as
Claude. Every price shows the date it was checked: prices change, so follow the link before you pay.

## Words, explained once

- **Account and plan:** your login with a company, and what you pay them.
- **API key** (or token): a long password that lets the Social Media Factory use a service as you. Whoever
  has it can spend your money there, so it lives only in your keys file. You can delete it and make a new
  one any time.
- **Keys file:** a plain text file in your Social Media Factory folder (`keys.env`) that only your
  computer reads. It is never uploaded.
- **Subscription, free plan, credit:** a subscription charges on a set date whatever you use. A free
  plan is never charged; paid plans of the same service are subscriptions. Prepaid credit runs out
  (sometimes slightly over). A reminder or an alert is never a limit.

## Always

- Keys go in your keys file, never in the chat, an email or a screenshot. Claude opens the file; you paste the key in yourself.
- If a key ever lands somewhere it shouldn't (a chat, an email, a screenshot, a recording): make a new key, delete the old one, and put the new one in your keys file.
- Screens on these websites change. If what you see doesn't match a step, take a screenshot with nothing private showing (no keys, passwords, codes or customer details) and ask Claude.

## At a glance

| Service | What it's for | Cost | How spending is limited |
|---|---|---|---|
| Claude | Running the Social Media Factory at all: you talk, it does the work on your computer | Claude Pro, about $20 a month before tax. | Subscription |
| Metricool | Scheduling posts and videos to your accounts, and reading how they did | The Advanced plan or higher: about $53 a month paid yearly ($636 a year) or $67 paid monthly, before tax. | Subscription |
| Apify | Research: what's working on YouTube, Instagram and TikTok, and what people ask on Reddit and X | A free plan with $5 of credit every month, no card needed. | Free plan; paid plans renew monthly |
| ElevenLabs | Turning speech into exact words, and telling speakers apart | About 22 cents per hour of audio. | Free plan; paid plans renew monthly |
| OpenAI (AI-made pictures) | AI-made pictures, only when you ask for one. Carousels and cards don't need it | An estimate of roughly 1 to 20 cents a picture, by size and quality, shown before each one. | Prepaid credit |

## Posting: four ways, in the order we suggest

1. **Post by hand from the ready-to-post folder.** No extra account or cost. Where everyone starts.
2. **Metricool,** when posting by hand becomes the bottleneck. Then build trust a step at a time: two
   scheduled posts first, check them the next day ("did my posts go out?"), then full scheduling.
3. **Direct apps with Meta, TikTok and YouTube: not offered yet.** Each platform wants weeks of paperwork,
   so don't start it for nothing.
4. **An AI posting through your browser: never.** It breaks every platform's rules, and the account can
   be banned without warning.

## Someone helping you set it up

Your business should own its own accounts, with a recovery email and phone it controls. A helper gets
their own login through the service's team or member invite where there is one, never your password. If
a helper pays for an account you use, they paste the key in with you there, and you don't change its
billing or plan.

## Claude

**What it does for you:** running the Social Media Factory at all: you talk, it does the work on your computer.

**Do you need it?** For everything. If you didn't pick any of those, skip it.

**What it costs:** Claude Pro, about $20 a month before tax. The free plan can't run the Social Media Factory. *(Checked 15 October 2026: [price page](https://claude.com/pricing).)*

**Limiting what you spend:** It's a subscription: it renews monthly whatever you use. Cancel any time in your Claude settings.

**Before you start:**

- An email address your business controls.
- Your phone, for security codes.
- A card, if you choose a paid plan.

**Step by step:**

1. Go to claude.ai and create an account with an email you'll keep. You'll get a code by email to confirm it.
2. Choose the Pro plan and pay by card. You'll see a confirmation that you're on Pro.
3. Download the Claude desktop app from claude.ai/download, install it and sign in.
4. Open the Code tab. That's the part that works with folders on your computer; the Social Media Factory runs there.

**Removing access:** To stop paying: Claude settings, then Billing, then cancel. Your Social Media Factory folder stays on your computer.

## Metricool

**What it does for you:** scheduling posts and videos to your accounts, and reading how they did.

**Do you need it?** For scheduling, one short a day, the TikTok test-and-promote loop, and checking results. If you didn't pick any of those, skip it.

**What it costs:** The Advanced plan or higher: about $53 a month paid yearly ($636 a year) or $67 paid monthly, before tax. The cheaper plans can't connect to the Social Media Factory. *(Checked 15 October 2026: [price page](https://metricool.com/pricing/).)*

**Limiting what you spend:** It's a subscription: it charges on the renewal date whether you post twice or two hundred times. Start monthly, the lower-risk choice, and set a calendar reminder a few days before it renews.

**Before you start:**

- Instagram: a Business or Creator account (in the Instagram app: Settings, then Account type and tools). Linking it to your Facebook Page gives Metricool fuller features.
- Facebook: you're an admin of the business's Page, not only of your personal profile.
- LinkedIn: for a company page, you're one of its admins. A personal profile works too.
- TikTok: your account name, or none yet.
- YouTube: which Google account owns the channel. It's often not the one you use every day.
- Your phone nearby for security codes, and two-step login turned on for each account.
- An email address your business controls.
- Your phone, for security codes.
- A card, if you choose a paid plan.

**Step by step:**

1. Check your social accounts are ready (the list above), so you don't pay before they can connect.
2. Go to metricool.com and sign up with an email your business controls. Turn on two-step login.
3. Choose the Advanced plan and pay by card. Monthly billing is the lower-risk start.
4. Create a brand in Metricool for your business: one Metricool brand for each brand in your Social Media Factory.
5. Connect each social account inside that brand. You log in to each platform yourself; your passwords never go to Claude or the Social Media Factory.
6. Find your key: in Metricool, Account settings, then API. Copy the token, and the user id shown on the same page.

**Add it.** Say *add my keys*. Your keys file opens in your own editor. Paste the API token after `METRICOOL_USER_TOKEN=` and the user id after `METRICOOL_USER_ID=`, with no spaces, then save, close the file and say *done*. Claude never reads it back.

**Check it.** Say *check my setup*. Each feature says **ready** (checked with the service), **unverified** (the key is there and gets checked the first time it's used, or now if you say *check my keys online*), **needs a key**, or **key not working** with the reason in plain words.

**If something goes wrong.** The usual causes: a space pasted with the key, the wrong key copied, or no credit left on the account. Take a screenshot with nothing private showing, and ask Claude.

**Removing access:** In Metricool: Account settings, then API. Make a new token and the old one stops working. To stop paying, cancel in Billing.

## Apify

**What it does for you:** research: what's working on YouTube, Instagram and TikTok, and what people ask on Reddit and X.

**Do you need it?** For research. If you didn't pick any of those, skip it.

**What it costs:** A free plan with $5 of credit every month, no card needed. The credit doesn't carry over. Every research run shows its estimated cost before it starts. *(Checked 15 October 2026: [price page](https://apify.com/pricing).)*

**Limiting what you spend:** On the free plan, research simply stops when the month's $5 is used up, and you're never charged. Paid plans are monthly subscriptions: they renew whatever you use. On a paid plan, also set a monthly usage limit in Settings, then Billing, so usage can't go past it.

**Before you start:**

- An email address your business controls.
- Your phone, for security codes.
- A card, if you choose a paid plan.

**Step by step:**

1. Go to apify.com and sign up. No card is needed for the free plan.
2. Find your key: in the Apify console, Settings, then API and Integrations. Copy the personal API token.

**Add it.** Say *add my keys*. Your keys file opens in your own editor. Paste the key after `APIFY_API_TOKEN=`, with no spaces, then save, close the file and say *done*. Claude never reads it back.

**Check it.** Say *check my setup*. Each feature says **ready** (checked with the service), **unverified** (the key is there and gets checked the first time it's used, or now if you say *check my keys online*), **needs a key**, or **key not working** with the reason in plain words.

**If something goes wrong.** The usual causes: a space pasted with the key, the wrong key copied, or no credit left on the account. Take a screenshot with nothing private showing, and ask Claude.

**Removing access:** In the Apify console: Settings, then API and Integrations. Delete the token, or make a new one.

## ElevenLabs

**What it does for you:** turning speech into exact words, and telling speakers apart.

**Do you need it?** For answering the onboarding page by voice, and clips from your recordings. If you didn't pick any of those, skip it.

**What it costs:** About 22 cents per hour of audio. The free plan includes about 30 minutes of transcription a month, enough to answer the onboarding page by voice. For clips and regular business use, choose the cheapest paid plan (about $6 a month when checked): the free plan may not include commercial use. *(Checked 15 October 2026: [price page](https://elevenlabs.io/pricing/api).)*

**Limiting what you spend:** The free plan is never charged: when its credit runs out, transcription stops until next month. Paid plans are monthly subscriptions that renew whatever you use; leave extra usage (usage-based billing) turned off so nothing is charged beyond the plan.

**Before you start:**

- An email address your business controls.
- Your phone, for security codes.
- A card, if you choose a paid plan.

**Step by step:**

1. Go to elevenlabs.io and sign up. Start on the free plan; you can move up later.
2. Leave extra usage (usage-based billing) off, so you can't be charged past your plan.
3. Find your key: your profile, then API keys, then Create. If it asks which permissions to give, allow speech to text. Copy the key.

**Add it.** Say *add my keys*. Your keys file opens in your own editor. Paste the key after `ELEVENLABS_API_KEY=`, with no spaces, then save, close the file and say *done*. Claude never reads it back.

**Check it.** Say *check my setup*. Each feature says **ready** (checked with the service), **unverified** (the key is there and gets checked the first time it's used, or now if you say *check my keys online*), **needs a key**, or **key not working** with the reason in plain words.

**If something goes wrong.** The usual causes: a space pasted with the key, the wrong key copied, or no credit left on the account. Take a screenshot with nothing private showing, and ask Claude.

**Removing access:** In ElevenLabs: your profile, then API keys. Delete the key.

## OpenAI (AI-made pictures)

**What it does for you:** AI-made pictures, only when you ask for one. Carousels and cards don't need it.

**Do you need it?** For AI-made pictures. If you didn't pick any of those, skip it.

**What it costs:** An estimate of roughly 1 to 20 cents a picture, by size and quality, shown before each one. It's a separate OpenAI developer account with its own billing, not a ChatGPT subscription. *(Checked 9 October 2026: [price page](https://developers.openai.com/api/docs/models/gpt-image-1.5).)*

**Limiting what you spend:** Add prepaid credit (for example $5) with automatic top-up turned off. When it runs out, pictures stop, though OpenAI may let it run slightly over first. A project budget and email alert only warn you; they don't stop spending.

**Before you start:**

- An email address your business controls.
- Your phone, for security codes.
- A card, if you choose a paid plan.

**Step by step:**

1. Go to platform.openai.com and sign up. This is separate from ChatGPT, even if you already have ChatGPT.
2. In Billing, add a small prepaid credit and turn automatic top-up off.
3. Find your key: API keys, then Create new secret key. Copy it straight away; it's only shown once.

**Add it.** Say *add my keys*. Your keys file opens in your own editor. Paste the key after `OPENAI_API_KEY=`, with no spaces, then save, close the file and say *done*. Claude never reads it back.

**Check it.** Say *check my setup*. Each feature says **ready** (checked with the service), **unverified** (the key is there and gets checked the first time it's used, or now if you say *check my keys online*), **needs a key**, or **key not working** with the reason in plain words. There's no free way to check this key, so “check my setup” shows it as unverified. That's expected.

**If something goes wrong.** The usual causes: a space pasted with the key, the wrong key copied, or no credit left on the account. Take a screenshot with nothing private showing, and ask Claude.

**Removing access:** In the OpenAI platform: API keys. Revoke the key.
