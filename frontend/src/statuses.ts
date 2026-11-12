// Shared, plain-language labels and meanings for the dashboard's distinct status domains.

import { toScaled } from './format.ts'

export type PaymentStatus = 'overdue' | 'pending' | 'advance' | 'settled' | 'no_bill'
export type PartyKind = 'customers' | 'vendors'
export type StatusTone = 'good' | 'bad' | 'neutral'

export interface StatusInfo {
  label: string
  meaning: string
  tone: StatusTone
}

export function paymentStatusInfo(status: unknown, kind: PartyKind): StatusInfo {
  const customer = kind === 'customers'
  if (status !== null && status !== undefined && typeof status !== 'string') {
    return {
      label: 'Other status',
      meaning: 'The source returned a payment status that is not recognized.',
      tone: 'neutral',
    }
  }
  const value = typeof status === 'string' ? status.trim().toLowerCase() : ''
  switch (value) {
    case 'overdue':
      return {
        label: customer ? 'Payment Overdue' : 'Payment to Supplier Overdue',
        meaning: customer
          ? 'Customer has not paid by the due date.'
          : 'Your company has not paid the supplier by the due date.',
        tone: 'bad',
      }
    case 'pending':
      return {
        label: customer ? 'Payment Pending' : 'Payment to Supplier Pending',
        meaning: customer
          ? 'Customer needs to pay, but the due date has not passed.'
          : 'Your company needs to pay the supplier, but the due date has not passed.',
        tone: 'neutral',
      }
    case 'advance':
      return {
        label: customer ? 'Customer Advance' : 'Supplier Advance',
        meaning: customer
          ? 'Customer has paid extra. This amount is available as credit.'
          : 'Your company has paid the supplier extra. This amount is available as credit.',
        tone: 'good',
      }
    case 'settled':
    case 'paid':
      return {
        label: 'Fully Settled',
        meaning: customer ? 'Customer has no outstanding payment.' : 'No outstanding supplier payment remains.',
        tone: 'good',
      }
    case 'due':
      return {
        label: customer ? 'Payment Pending' : 'Payment to Supplier Pending',
        meaning: customer
          ? 'Customer needs to pay, but the due date has not passed.'
          : 'Your company needs to pay the supplier, but the due date has not passed.',
        tone: 'neutral',
      }
    case 'no_bill':
      return {
        label: 'No bill details',
        meaning: 'There is no bill-wise allocation to determine a payment status.',
        tone: 'neutral',
      }
    case 'mixed':
      return {
        label: 'Multiple bill statuses',
        meaning: customer
          ? 'Some bills are overdue while others are not yet due or are available as credit.'
          : 'Supplier bills have different due or credit states; review each bill before paying.',
        tone: 'neutral',
      }
    case 'current':
      return {
        label: 'No bill details',
        meaning: 'There is no bill-wise allocation to determine a payment status.',
        tone: 'neutral',
      }
    default:
      if (!value) {
        return {
          label: 'Not available',
          meaning: 'The source did not provide a payment status.',
          tone: 'neutral',
        }
      }
      return {
        label: 'Other status',
        meaning: 'The source returned a payment status that is not recognized.',
        tone: 'neutral',
      }
  }
}

export function partyPaymentStatusInfo(
  status: unknown,
  balance: unknown,
  kind: PartyKind,
): StatusInfo {
  const amount =
    typeof balance === 'string' && /^-?\d+(?:\.\d+)?$/.test(balance.trim())
      ? toScaled(balance)
      : undefined

  if (amount !== undefined && amount <= -50n) return paymentStatusInfo('advance', kind)
  if (amount !== undefined && amount < 50n) return paymentStatusInfo('settled', kind)

  const value = typeof status === 'string' ? status.trim().toLowerCase() : ''
  if (!value || value === 'current') return paymentStatusInfo('no_bill', kind)
  if (amount !== undefined && amount > 0n && (value === 'advance' || value === 'settled' || value === 'paid')) {
    return paymentStatusInfo('no_bill', kind)
  }
  return paymentStatusInfo(status, kind)
}

export function validationStatusInfo(status: string | null | undefined): StatusInfo {
  if (status === 'passed') {
    return {
      label: 'Passed',
      meaning: 'The latest validation found no differences or failed checks.',
      tone: 'good',
    }
  }
  if (status === 'failed') {
    return {
      label: 'Failed',
      meaning: 'The latest validation found one or more differences or failed checks.',
      tone: 'bad',
    }
  }
  if (status === 'running') {
    return {
      label: 'In progress',
      meaning: 'A validation run is currently underway.',
      tone: 'neutral',
    }
  }
  if (status) {
    return {
      label: 'Other status',
      meaning: 'The source returned a validation status that is not recognized.',
      tone: 'neutral',
    }
  }
  return {
    label: 'Not checked',
    meaning: 'No completed validation result is available yet.',
    tone: 'neutral',
  }
}

export function sourceStatusInfo(loaded: unknown): StatusInfo {
  if (loaded === true) {
    return { label: 'Loaded', meaning: 'The source reported this company as loaded at its last check.', tone: 'good' }
  }
  if (loaded === false) {
    return { label: 'Not loaded', meaning: 'The source reported this company was not loaded at its last check.', tone: 'bad' }
  }
  if (loaded === null || loaded === undefined) {
    return { label: 'Not asked', meaning: 'The source has not yet been checked for this company.', tone: 'neutral' }
  }
  return {
    label: 'Other status',
    meaning: 'The source returned a loaded status that is not recognized.',
    tone: 'neutral',
  }
}

/** A status as one line for a hover on a row's label ("Payment Overdue: Customer has not paid by
 *  the due date."): the tables have no Status or Meaning column (docs/design/dashboard.md 0.4). */
export function statusHint(status: StatusInfo, timing = ''): string {
  return `${status.label}${timing}: ${status.meaning}`
}
