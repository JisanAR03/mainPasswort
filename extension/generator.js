// Password generator for extension-only mode ([S]). A port of
// app/src/personal_vault/core/generator.py; randomness only from
// crypto.getRandomValues, with rejection sampling so every character is
// equally likely.

const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const LOWER = "abcdefghijklmnopqrstuvwxyz";
const DIGITS = "0123456789";
const SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/|~";
const LOOKALIKES = new Set("0Oo1lI|");
const MAX_LENGTH = 4096;

// A uniform integer in [0, n), like secrets.randbelow.
function randbelow(n) {
  const limit = Math.floor(0x100000000 / n) * n;
  const word = new Uint32Array(1);
  for (;;) {
    crypto.getRandomValues(word);
    if (word[0] < limit) return word[0] % n;
  }
}

const choice = (pool) => pool[randbelow(pool.length)];

export function generatePassword({
  length = 20,
  upper = true,
  lower = true,
  digits = true,
  symbols = true,
  excludeLookalikes = true,
} = {}) {
  if (!Number.isInteger(length) || length < 4 || length > MAX_LENGTH) {
    throw new Error(`length must be 4-${MAX_LENGTH}`);
  }
  let pools = [];
  if (upper) pools.push(UPPER);
  if (lower) pools.push(LOWER);
  if (digits) pools.push(DIGITS);
  if (symbols) pools.push(SYMBOLS);
  if (pools.length === 0) throw new Error("at least one character class must be enabled");
  if (length < pools.length) throw new Error("length must be at least the number of classes");
  if (excludeLookalikes) {
    pools = pools.map((pool) => [...pool].filter((c) => !LOOKALIKES.has(c)).join(""));
  }
  const combined = pools.join("");
  const chars = pools.map(choice);
  while (chars.length < length) chars.push(choice(combined));
  for (let i = chars.length - 1; i > 0; i -= 1) {
    const j = randbelow(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}
