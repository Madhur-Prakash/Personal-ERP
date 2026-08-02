/**
 * Card presentation and the one check worth doing client-side.
 *
 * A plain module, not a component file: shared by the panel on Billing and by the Accounts
 * page, and a file that exports both components and helpers breaks fast refresh for
 * everything in it.
 */
import type { CardNetwork } from '@/features/billing/api';

export const NETWORK_LABELS: Record<CardNetwork, string> = {
  visa: 'Visa',
  mastercard: 'Mastercard',
  rupay: 'RuPay',
  amex: 'Amex',
  discover: 'Discover',
  diners: 'Diners Club',
  jcb: 'JCB',
  maestro: 'Maestro',
  // Not "Unknown": the card works perfectly well, the software just does not claim to
  // recognise the scheme from its leading digits.
  other: 'Card',
};

/** The range real card numbers fall in - ISO/IEC 7812, and the shortest Maestro. */
const MIN_DIGITS = 12;
const MAX_DIGITS = 19;

/** Strip the separators a person types or pastes. */
export function normaliseCardNumber(raw: string): string {
  return raw.replace(/[\s-]/g, '');
}

/**
 * Length and character check, kept separate from {@link passesLuhn}.
 *
 * The split lets a form tell "that is not a card number" from "that is a card number with a
 * typo in it", which are different things to say to someone - and stops it complaining
 * about a check digit before they have finished typing.
 */
export function isPlausibleCardNumber(digits: string): boolean {
  return digits.length >= MIN_DIGITS && digits.length <= MAX_DIGITS && /^\d+$/.test(digits);
}

/**
 * The Luhn check digit, so a typo is caught before a round trip.
 *
 * A duplicate of the server's check, deliberately: the server stays the authority, this
 * only saves someone a request to be told they mistyped one digit. Safe to duplicate
 * because Luhn is a fixed algorithm that cannot drift - unlike the issuer-range table that
 * names the scheme, which is left entirely to the server.
 */
export function passesLuhn(digits: string): boolean {
  if (!/^\d+$/.test(digits)) return false;

  let total = 0;
  // Doubling every second digit from the right, so the parity depends on the length.
  const parity = digits.length % 2;
  for (let index = 0; index < digits.length; index += 1) {
    let value = Number(digits[index]);
    if (index % 2 === parity) {
      value *= 2;
      if (value > 9) value -= 9;
    }
    total += value;
  }
  return total % 10 === 0;
}
