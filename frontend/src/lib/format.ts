/**
 * Formatting helpers.
 *
 * `Intl` formatters are cached: constructing one costs roughly as much as
 * formatting a hundred values, and a data table calls these per cell per render.
 */

const currencyCache = new Map<string, Intl.NumberFormat>();

function currencyFormatter(currency: string, locale: string): Intl.NumberFormat {
  const key = `${locale}:${currency}`;
  let formatter = currencyCache.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    });
    currencyCache.set(key, formatter);
  }
  return formatter;
}

/** Format money. Defaults to INR/en-IN, which lakh-groups (₹1,20,000). */
export function formatCurrency(amount: number, currency = 'INR', locale = 'en-IN'): string {
  return currencyFormatter(currency, locale).format(amount);
}

/** Abbreviate a large number for a KPI tile: 1.2K, 3.4M, 1.1Cr. */
export function formatCompact(value: number, locale = 'en-IN'): string {
  return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(
    value,
  );
}

export function formatNumber(value: number, locale = 'en-IN'): string {
  return new Intl.NumberFormat(locale).format(value);
}

export function formatPercent(value: number, fractionDigits = 1): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(fractionDigits)}%`;
}

export function formatDate(value: string | Date, locale = 'en-IN'): string {
  const date = typeof value === 'string' ? new Date(value) : value;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date);
}

export function formatDateTime(value: string | Date, locale = 'en-IN'): string {
  const date = typeof value === 'string' ? new Date(value) : value;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

/**
 * Relative time ("3 minutes ago"). Used in audit trails and session lists,
 * where the elapsed interval matters more than the absolute timestamp.
 */
export function formatRelative(value: string | Date, locale = 'en'): string {
  const date = typeof value === 'string' ? new Date(value) : value;
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

  const divisions: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, 'second'],
    [60, 'minute'],
    [24, 'hour'],
    [7, 'day'],
    [4.34524, 'week'],
    [12, 'month'],
    [Number.POSITIVE_INFINITY, 'year'],
  ];

  let value_ = seconds;
  for (const [amount, unit] of divisions) {
    if (Math.abs(value_) < amount) return rtf.format(Math.round(value_), unit);
    value_ /= amount;
  }
  return rtf.format(Math.round(value_), 'year');
}

/** Two-letter initials for an avatar fallback. */
export function initials(name: string, fallback = '?'): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return fallback;
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Format a money value that arrived from the API as a decimal **string**.
 *
 * The backend serialises money as a string on purpose: a JSON number is an
 * IEEE-754 double in JavaScript, so `1234567.89` would arrive as
 * `1234567.8899999999`. Passing that string straight to `formatCurrency` would
 * undo the whole point by calling `Number()` on it.
 *
 * `Intl.NumberFormat` accepts a string directly and formats it exactly, with no
 * float conversion anywhere in the path.
 */
export function formatMoney(
  value: string | null | undefined,
  currency = 'INR',
  locale = 'en-IN',
): string {
  if (value === null || value === undefined || value === '')
    return currencyFormatter(currency, locale).format(0);
  return currencyFormatter(currency, locale).format(value as unknown as number);
}

/**
 * Compare two API money strings without converting to `number`.
 *
 * Returns a negative number, zero, or a positive number, like a comparator.
 * Used for sorting and for sign checks (is this balance negative?).
 */
export function compareMoney(a: string, b: string): number {
  const left = BigInt(scaleToInteger(a));
  const right = BigInt(scaleToInteger(b));
  return left < right ? -1 : left > right ? 1 : 0;
}

/** True when an API money string represents zero, whatever its scale. */
export function isZeroMoney(value: string | null | undefined): boolean {
  if (!value) return true;
  return /^-?0*(\.0*)?$/.test(value.trim());
}

/** True when an API money string is negative. */
export function isNegativeMoney(value: string | null | undefined): boolean {
  return !!value && value.trim().startsWith('-');
}

/**
 * Normalise a decimal string to a fixed-scale integer string, so two values of
 * differing scale ("0" and "0.0000") compare equal.
 */
function scaleToInteger(value: string, scale = 6): string {
  const trimmed = value.trim();
  const negative = trimmed.startsWith('-');
  const [whole, fraction = ''] = trimmed.replace(/^[-+]/, '').split('.');
  const padded = (fraction + '0'.repeat(scale)).slice(0, scale);
  return `${negative ? '-' : ''}${whole}${padded}`;
}
