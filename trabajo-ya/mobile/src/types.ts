export type Tab = 'assistant' | 'applications' | 'searches' | 'profile';
export type Frequency = 'daily' | 'weekly';
export interface Profile {
  full_name: string; city: string; headline: string; photo_path?: string | null;
  experiences: { id: string; company: string; role: string; description: string; start_date?: string; end_date?: string | null }[];
  credentials: { id: string; name: string; issuer: string; kind: string }[];
  references: { id: string; full_name: string; relationship: string; contact: string; consent_to_contact: boolean }[];
}
export interface Resume { id: string; name: string; file_name: string; storage_path: string; mime_type: string; size_bytes: number; created_at: string; is_default: boolean; demo?: boolean }
export interface SearchProposal { title: string; role: string; city: string; frequency: Frequency; time: string; timezone: string; weekdays: number[]; mode: 'manual' | 'automatic'; resume_id?: string }
export interface JobSearch { id: string; name: string; roles: string[]; cities: string[]; schedule_time: string; timezone: string; frequency: Frequency; weekdays: number[]; status: 'enabled' | 'paused'; auto_apply: boolean; next_run_at: string | null; last_run_at?: string | null; preferred_resume_id?: string | null; consent_id?: string | null; consent_expires_at?: string | null; consent_revoked_at?: string | null; consent_repeat_every_days?: 0 | 3 | null; consent_daily_limit?: number | null; demo?: boolean }
export interface Application { id: string; company: string; role: string; recipient_email: string; subject: string; body: string; resume_id: string | null; status: 'pending' | 'sent' | 'error' | 'responded'; created_at: string; provider_message_id: string | null; provider_confirmed_at: string | null; parent_application_id?: string | null; delivery_sequence?: number; job_match_id?: string | null; sending_consent_id?: string | null; sender_email?: string | null; send_attempt_id?: string | null; attempted_at?: string | null; sent_at?: string | null; delivery_uncertain?: boolean; followups_stopped?: boolean; followups_stopped_at?: string | null; followups_stop_reason?: string | null; error_message?: string | null; demo?: boolean }
export interface ChatMessage { id: string; role: 'assistant' | 'user'; content: string; created_at: string; proposal?: SearchProposal; saved?: boolean; demo?: boolean }
export interface Health { mode: string; ai: string; source: string; mail: string; scheduler: string }
export interface MailConnection { id: string; email: string; provider: 'google' | 'microsoft'; status: 'connected' | 'disconnected' | 'expired' }
export interface AppState { profile: Profile; resumes: Resume[]; searches: JobSearch[]; applications: Application[]; messages: ChatMessage[]; email_connections?: MailConnection[] }
export interface Notice { text: string; kind: 'success' | 'error' | 'info' }
