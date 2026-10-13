/** Only this non-sensitive appearance preference is saved on the device. */
export const THEME_PREFERENCE_KEY = 'trabajo-ya.theme-preference';

export type ThemePreference = 'light' | 'dark' | 'system';
export interface ThemePreferenceState {
  preference: ThemePreference;
  ready: boolean;
  selectedDuringHydration: boolean;
}
export type ThemePreferenceAction =
  | { type: 'select'; preference: ThemePreference }
  | { type: 'hydrate'; saved: unknown };

export function readPreference(saved: unknown, fallback: ThemePreference = 'system'): ThemePreference {
  return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : fallback;
}

export function initialPreferenceState(initialDark?: boolean): ThemePreferenceState {
  return {
    preference: initialDark === undefined ? 'system' : initialDark ? 'dark' : 'light',
    ready: false,
    selectedDuringHydration: false,
  };
}

export function preferenceReducer(state: ThemePreferenceState, action: ThemePreferenceAction): ThemePreferenceState {
  if (action.type === 'select') {
    return { ...state, preference: action.preference, selectedDuringHydration: !state.ready };
  }
  return {
    ...state,
    ready: true,
    preference: state.selectedDuringHydration ? state.preference : readPreference(action.saved, state.preference),
  };
}

export function isDarkTheme(preference: ThemePreference, deviceTheme: string | null | undefined): boolean {
  return preference === 'dark' || (preference === 'system' && deviceTheme === 'dark');
}
