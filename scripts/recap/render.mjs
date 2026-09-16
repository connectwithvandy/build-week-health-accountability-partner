/**
 * Render one recap card to a PNG.
 *
 *   node scripts/recap/render.mjs '<json>' out.png
 *
 * `next/og` is imported by file path because Next 16 ships no exports map, so
 * the bare specifier "next/og" does not resolve under Node's ESM resolver.
 *
 * Fonts are the site's own, fetched as TTF. Google Fonts serves a format per
 * user agent: the default gets woff2 and an IE string gets EOT, neither of
 * which satori can parse, so the request deliberately sends no agent at all.
 */
import { ImageResponse } from "next/og.js";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { recapCard } from "./card.mjs";

const FONT_DIR = process.env.RECAP_FONT_DIR || ".recap-fonts";
const FONTS = [
  ["fraunces900.ttf", "Fraunces", 900, "Fraunces:wght@900"],
  ["outfit800.ttf", "Outfit", 800, "Outfit:wght@800"],
  ["outfit600.ttf", "Outfit", 600, "Outfit:wght@600"],
  ["outfit400.ttf", "Outfit", 400, "Outfit:wght@400"],
];

async function font(file, spec) {
  const path = `${FONT_DIR}/${file}`;
  if (!existsSync(path)) {
    mkdirSync(FONT_DIR, { recursive: true });
    const css = await (await fetch(`https://fonts.googleapis.com/css2?family=${spec}`)).text();
    const url = css.match(/https:\/\/fonts\.gstatic\.com\/[^)]*/)[0];
    writeFileSync(path, Buffer.from(await (await fetch(url)).arrayBuffer()));
  }
  return readFileSync(path);
}

const data = JSON.parse(process.argv[2] || "{}");
const out = process.argv[3] || "recap.png";

const image = new ImageResponse(recapCard(data), {
  width: 1080,
  height: 1350,
  fonts: await Promise.all(
    FONTS.map(async ([file, name, weight, spec]) => ({
      name,
      weight,
      style: "normal",
      data: await font(file, spec),
    })),
  ),
});
const buffer = Buffer.from(await image.arrayBuffer());
writeFileSync(out, buffer);
console.log(`wrote ${out} (${(buffer.length / 1024).toFixed(0)} kB)`);
