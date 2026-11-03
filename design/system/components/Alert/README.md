# Alert

A short time-bound warning, mostly about prices and injuries.

- `orange-tint` for a target likely to rise, `red-tint` for a player you own likely to fall or newly flagged injured. Text in the matching ink, one sentence in `body`, with the time in IST.
- A 10px dot in the stronger shade leads the line; it is decoration, the words carry the meaning.
- `radius-md`, padding 14px by 16px, `role="status"`.
- Only alerts that need action. A rise on a player you already own is not an alert.
