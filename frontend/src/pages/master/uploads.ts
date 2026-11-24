import { t } from '../../i18n/lv'
import type { QualificationType } from '../../types/capabilities'

// The API's upload limits (backend app/services/uploads.py, R-MST-15), checked here only so the master learns
// about them before sending. The backend checks everything again and detects the real format from the content.
export const MAX_FILES = 5
export const MAX_FILE_BYTES = 10 * 1024 * 1024
const TYPES = new Set(['application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'])
const EXTENSIONS = new Set(['pdf', 'jpg', 'jpeg', 'png', 'webp', 'heic'])
export const ACCEPT = '.pdf,.jpg,.jpeg,.png,.webp,.heic,application/pdf,image/jpeg,image/png,image/webp,image/heic'

const tf = t.capabilities.fileErrors

/** Problems with the selected files, in Latvian (empty = none). */
export function fileProblems(files: File[]): string[] {
  const problems: string[] = []
  if (files.length > MAX_FILES) problems.push(tf.tooMany)
  for (const file of files) {
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    // Browsers often report HEIC without a type; the extension is then the only hint.
    if (!TYPES.has(file.type) && !EXTENSIONS.has(extension)) problems.push(tf.type(file.name))
    else if (file.size === 0) problems.push(tf.empty(file.name))
    else if (file.size > MAX_FILE_BYTES) problems.push(tf.tooLarge(file.name))
  }
  return problems
}

/** The qualification type's own required fields (its rules come from the API). */
export function missingFields(
  rule: QualificationType,
  form: { documentNumber: string; validUntil: string; files: File[] },
): string[] {
  const missing: string[] = []
  if (rule.requires_document && form.files.length === 0) missing.push(tf.documentRequired)
  if (rule.requires_document_number && !form.documentNumber.trim()) missing.push(tf.numberRequired)
  if (rule.requires_expiry_date && !form.validUntil) missing.push(tf.expiryRequired)
  return missing
}
