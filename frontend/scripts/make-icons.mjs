// Renders the PWA icons from the candle mark in app/icon.svg.
//
// The mark is redrawn here rather than rasterised from the favicon file: that
// file has its own rounded background and 32px-tuned stroke. Android masks
// launcher icons itself, so these are square, and the maskable variant keeps the
// mark inside the central 50% so no mask shape clips it.
import { mkdir } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import sharp from "sharp"

const BG = "#040609"
const INK = "#7af0ce"
const OUT = fileURLToPath(new URL("../public/icons/", import.meta.url))

function candle(size, scale) {
  const s = (size * scale) / 32
  const offset = (size - 32 * s) / 2
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" fill="${BG}"/>
  <g transform="translate(${offset} ${offset}) scale(${s})" stroke="${INK}" stroke-width="3" stroke-linecap="butt">
    <line x1="16" y1="3" x2="16" y2="29"/>
    <rect x="9.5" y="11" width="13" height="10" fill="${BG}"/>
  </g>
</svg>`
}

async function write(name, size, scale) {
  await sharp(Buffer.from(candle(size, scale))).png().toFile(`${OUT}${name}`)
  console.log(`wrote public/icons/${name}`)
}

await mkdir(OUT, { recursive: true })

await write("icon-192.png", 192, 0.7)
await write("icon-512.png", 512, 0.7)
await write("icon-512-maskable.png", 512, 0.5)
