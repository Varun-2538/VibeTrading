import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"
import { dirname } from "node:path"

const sharp = createRequire(new URL("../frontend/package.json", import.meta.url))("sharp")
const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const BG = "#040609"
const INK = "#7af0ce"
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="500" viewBox="0 0 1024 500">
  <rect width="1024" height="500" fill="${BG}"/>
  <g transform="translate(300 122) scale(8)" stroke="${INK}" stroke-width="3">
    <line x1="16" y1="3" x2="16" y2="29"/>
    <rect x="9.5" y="11" width="13" height="10" fill="${BG}"/>
  </g>
  <text x="600" y="235" fill="#f7f7fa" font-family="Arial, Helvetica, sans-serif" font-size="72" font-weight="700" text-anchor="middle">VibeTrading</text>
  <text x="600" y="290" fill="#9aa0ad" font-family="Arial, Helvetica, sans-serif" font-size="28" text-anchor="middle">Levels and patterns, scoped to your chart</text>
</svg>`

await sharp(Buffer.from(svg)).png().toFile(`${__dirname}/feature-graphic.png`)
console.log("wrote store/feature-graphic.png")
