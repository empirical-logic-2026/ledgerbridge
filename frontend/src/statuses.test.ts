import { describe, expect, it } from 'vitest'
import { partyPaymentStatusInfo, paymentStatusInfo, sourceStatusInfo, validationStatusInfo } from './statuses.ts'

describe('dashboard status wording', () => {
  it('explains each customer outstanding state without classifying an advance as overdue', () => {
    expect(paymentStatusInfo('overdue', 'customers')).toEqual({
      label: 'Payment Overdue',
      meaning: 'Customer has not paid by the due date.',
      tone: 'bad',
    })
    expect(paymentStatusInfo('pending', 'customers').label).toBe('Payment Pending')
    expect(paymentStatusInfo('advance', 'customers').label).toBe('Customer Advance')
    expect(paymentStatusInfo('settled', 'customers').label).toBe('Fully Settled')
    expect(paymentStatusInfo('no_bill', 'customers')).toMatchObject({
      label: 'No bill details',
      meaning: 'There is no bill-wise allocation to determine a payment status.',
    })
    expect(paymentStatusInfo('due', 'customers').label).toBe('Payment Pending')
    expect(paymentStatusInfo('paid', 'customers').label).toBe('Fully Settled')
    expect(paymentStatusInfo('current', 'customers').label).toBe('No bill details')
  })

  it('uses supplier-specific names and plain-language meanings', () => {
    expect(paymentStatusInfo('overdue', 'vendors')).toEqual({
      label: 'Payment to Supplier Overdue',
      meaning: 'Your company has not paid the supplier by the due date.',
      tone: 'bad',
    })
    expect(paymentStatusInfo('pending', 'vendors')).toEqual({
      label: 'Payment to Supplier Pending',
      meaning: 'Your company needs to pay the supplier, but the due date has not passed.',
      tone: 'neutral',
    })
    expect(paymentStatusInfo('advance', 'vendors')).toEqual({
      label: 'Supplier Advance',
      meaning: 'Your company has paid the supplier extra. This amount is available as credit.',
      tone: 'good',
    })
    expect(paymentStatusInfo('settled', 'vendors')).toEqual({
      label: 'Fully Settled',
      meaning: 'No outstanding supplier payment remains.',
      tone: 'good',
    })
    expect(paymentStatusInfo('no_bill', 'vendors').label).toBe('No bill details')
    expect(paymentStatusInfo('mixed', 'vendors')).toEqual({
      label: 'Multiple bill statuses',
      meaning: 'Supplier bills have different due or credit states; review each bill before paying.',
      tone: 'neutral',
    })
    expect(validationStatusInfo('failed').label).toBe('Failed')
    expect(validationStatusInfo('failed').meaning).toContain('validation')
    expect(sourceStatusInfo(false).label).toBe('Not loaded')
    expect(sourceStatusInfo(false).meaning).toContain('source reported')
  })

  it('classifies party summaries using normalized balances before legacy statuses', () => {
    expect(partyPaymentStatusInfo('overdue', '100.00', 'customers').label).toBe('Payment Overdue')
    expect(partyPaymentStatusInfo('pending', '100.00', 'customers').label).toBe('Payment Pending')
    expect(partyPaymentStatusInfo('overdue', '-100.00', 'customers').label).toBe('Customer Advance')
    expect(partyPaymentStatusInfo('overdue', '0.00', 'customers').label).toBe('Fully Settled')
    expect(partyPaymentStatusInfo('overdue', '-100.00', 'vendors').label).toBe('Supplier Advance')
    expect(partyPaymentStatusInfo('pending', '100.00', 'vendors').label).toBe('Payment to Supplier Pending')
    expect(partyPaymentStatusInfo('mixed', '100.00', 'vendors').label).toBe('Multiple bill statuses')
    expect(partyPaymentStatusInfo('current', '100.00', 'vendors').label).toBe('No bill details')
    expect(partyPaymentStatusInfo(undefined, '0.004', 'vendors').label).toBe('Fully Settled')
    expect(partyPaymentStatusInfo(undefined, '100.00', 'vendors').label).toBe('No bill details')
  })

  it('keeps validation and source statuses in their own domains', () => {
    expect(validationStatusInfo('failed').label).toBe('Failed')
    expect(validationStatusInfo('failed').meaning).toContain('validation')
    expect(sourceStatusInfo(false).label).toBe('Not loaded')
    expect(sourceStatusInfo(false).meaning).toContain('source reported')
  })

  it('reserves Not available for absent status information and handles unknown values separately', () => {
    for (const status of [undefined, null, '']) {
      expect(paymentStatusInfo(status, 'customers')).toEqual({
        label: 'Not available',
        meaning: 'The source did not provide a payment status.',
        tone: 'neutral',
      })
    }
    expect(paymentStatusInfo('unexpected_status', 'customers')).toEqual({
      label: 'Other status',
      meaning: 'The source returned a payment status that is not recognized.',
      tone: 'neutral',
    })
  })

  it('maps every validation and source-loaded category without borrowing payment meanings', () => {
    expect(validationStatusInfo('passed')).toMatchObject({ label: 'Passed', tone: 'good' })
    expect(validationStatusInfo('failed')).toMatchObject({ label: 'Failed', tone: 'bad' })
    expect(validationStatusInfo('running')).toMatchObject({ label: 'In progress', tone: 'neutral' })
    expect(validationStatusInfo(null)).toMatchObject({ label: 'Not checked', tone: 'neutral' })
    expect(validationStatusInfo('new_state')).toMatchObject({ label: 'Other status', tone: 'neutral' })
    expect(sourceStatusInfo(true)).toMatchObject({ label: 'Loaded', tone: 'good' })
    expect(sourceStatusInfo(false)).toMatchObject({ label: 'Not loaded', tone: 'bad' })
    expect(sourceStatusInfo(null)).toMatchObject({ label: 'Not asked', tone: 'neutral' })
    expect(sourceStatusInfo('unknown')).toMatchObject({ label: 'Other status', tone: 'neutral' })
  })

  it('does not turn unsupported values into missing status data', () => {
    expect(paymentStatusInfo(42, 'customers')).toEqual({
      label: 'Other status',
      meaning: 'The source returned a payment status that is not recognized.',
      tone: 'neutral',
    })
  })
})
