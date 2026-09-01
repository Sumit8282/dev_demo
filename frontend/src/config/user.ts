export interface AppUser {
  name: string;
  email: string;
  soeId: string;
}

/** Fallback used only when auth context is unavailable (e.g. tests). */
export const FALLBACK_USER: AppUser = {
  name: 'Gauri Satalkar',
  email: 'satalkar_g@citi.com',
  soeId: 'satalkar_g',
} as const;

/** @deprecated Use useAuth().user instead */
export const CURRENT_USER = FALLBACK_USER;
