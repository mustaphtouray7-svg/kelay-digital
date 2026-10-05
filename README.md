# Kelay Digital

A responsive, single-page business website for Kelay Digital, built with plain HTML, CSS, and JavaScript. It presents the studio's services, original sample portfolio concepts, company introduction, and contact information.

## Run locally

No build tools or package installation are needed. Open `index.html` in a browser, or start a local static server from this folder:

```powershell
py -m http.server 8000
```

Then visit [http://localhost:8000](http://localhost:8000).

## Customize contact details

Open `script.js` and update the `CONTACT_DETAILS` object:

```js
const CONTACT_DETAILS = {
  email: "hello@example.com",
  whatsappNumber: "12345678900"
};
```

Use an international WhatsApp number with its country code and digits only. Until these values are set, the website clearly marks contact links as not yet available rather than linking to a nonfunctional placeholder.

## Site structure

- `index.html` — accessible page structure, search metadata, and site content.
- `styles.css` — responsive layout, visual styling, and reduced-motion support.
- `script.js` — mobile navigation, configurable contact links, and current year.
- `assets/favicon.svg` — custom Kelay Digital favicon.

The Goodday Café, Fieldnote Studio, and Daylight portfolio entries are original **sample concepts**, not claims about client work. Their visual illustrations are drawn in HTML and CSS; no stock or client imagery is used. The page uses DM Sans and Manrope via Google Fonts, with local system font fallbacks.
