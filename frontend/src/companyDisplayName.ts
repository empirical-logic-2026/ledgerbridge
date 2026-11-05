// One display rule for company names: use the deployment-configured label, else the source name.

import type { Company } from './api/types.ts'

export function companyDisplayName(company: Pick<Company, 'name' | 'display_name'>): string {
  return company.display_name.trim() || company.name
}
