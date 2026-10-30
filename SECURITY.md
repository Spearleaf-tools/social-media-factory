# Security

## Reporting a problem

If you find a way the Social Media Factory could leak a key, post something without a yes, mix up two
brands, or run something it shouldn't, please tell us privately:

1. Open the **Security** tab of this repository.
2. Choose **Report a vulnerability** and describe what you found and how to see it happen.

Please don't open a public issue for it, and never paste a real key, password or customer detail into a
report. Use made-up values. We reply as soon as we can and say when a fix is out.

## What the Social Media Factory promises

- **Your keys stay on your computer.** They live in one file (`keys.env`) that is never uploaded and
  that Claude is told not to read. Guards stop commands and replies that would show a key.
- **Your brand stays on your computer.** Everything in the `Client` folder is kept out of version
  control, except the made-up example bakery.
- **Nothing goes out without your yes.** A preview sends nothing at all.

## If a key gets out

Make a new key at the service, delete the old one there, and put the new one in your keys file.
`HELP.md` has the steps ("Replace a key").

## Supported versions

Only the latest release gets fixes. Download it from the Releases page.
