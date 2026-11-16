/**
 * Offsets come from Python, which counts code points; JavaScript strings
 * count UTF-16 units. Convert only when the text has astral characters.
 */
export function splitAtCodePoints(text: string, start: number, end: number): [string, string, string] {
  if (!/[\uD800-\uDFFF]/.test(text)) {
    return [text.slice(0, start), text.slice(start, end), text.slice(end)];
  }
  const points = Array.from(text);
  return [points.slice(0, start).join(""), points.slice(start, end).join(""), points.slice(end).join("")];
}
