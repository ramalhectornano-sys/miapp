import React, { createContext, useCallback, useContext, useEffect, useReducer, useRef } from 'react';
import { useColorScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  initialPreferenceState,
  isDarkTheme,
  preferenceReducer,
  THEME_PREFERENCE_KEY,
  ThemePreference,
} from './preference';

export type { ThemePreference } from './preference';

const light = {
  bg: '#F6F7F3', surface: '#FFFFFF', surfaceAlt: '#F0F3EE', text: '#192D2A', muted: '#76827C',
  border: '#E2E7E0', primary: '#277253', primarySoft: '#E6F0E7', onPrimary: '#FFFFFF',
  danger: '#BE4B4B', warning: '#AD7732', info: '#557D9C', shadow: '#1A3527',
};
const night: typeof light = {
  bg: '#12211D', surface: '#1A2B25', surfaceAlt: '#23372F', text: '#E8EFE8', muted: '#9CAA9F',
  border: '#30443A', primary: '#83BA91', primarySoft: '#294837', onPrimary: '#132B1D',
  danger: '#EE9696', warning: '#DCC08F', info: '#9BBBD2', shadow: '#000000',
};
export type Colors = typeof light;
export interface ThemeValue {
  colors: Colors;
  dark: boolean;
  toggle: () => void;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  ready: boolean;
}
const ThemeContext = createContext<ThemeValue>({
  colors: light, dark: false, toggle: () => {}, preference: 'system', setPreference: () => {}, ready: false,
});
export function ThemeProvider({ children, initialDark }: { children: React.ReactNode; initialDark?: boolean }) {
  const systemTheme = useColorScheme();
  const [state, dispatch] = useReducer(preferenceReducer, initialDark, initialPreferenceState);
  const storageQueue = useRef<Promise<void>>(Promise.resolve());
  const dark = isDarkTheme(state.preference, systemTheme);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const saved = await AsyncStorage.getItem(THEME_PREFERENCE_KEY);
        if (active) dispatch({ type: 'hydrate', saved });
      } catch {
        if (active) dispatch({ type: 'hydrate', saved: null });
      }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!state.ready) return;
    // Serialize rapid selections so an older write cannot replace the latest one.
    storageQueue.current = storageQueue.current
      .then(() => AsyncStorage.setItem(THEME_PREFERENCE_KEY, state.preference))
      .catch(() => { /* The current theme still works if device storage is unavailable. */ });
  }, [state.ready, state.preference]);

  const setPreference = useCallback((preference: ThemePreference) => dispatch({ type: 'select', preference }), []);
  const toggle = useCallback(() => setPreference(dark ? 'light' : 'dark'), [dark, setPreference]);

  return (
    <ThemeContext.Provider value={{
      colors: dark ? night : light, dark, toggle,
      preference: state.preference, setPreference, ready: state.ready,
    }}>
      {children}
    </ThemeContext.Provider>
  );
}
export function useTheme() { return useContext(ThemeContext); }

export const spacing = { xs: 6, sm: 12, md: 20, lg: 28, xl: 40 };
export const radius = { sm: 9, md: 16, lg: 22, pill: 999 };
