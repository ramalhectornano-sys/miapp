import React from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, TextInput, View, type KeyboardTypeOptions, type StyleProp, type ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/theme';

type IconName = React.ComponentProps<typeof Ionicons>['name'];
export function Button({ label, onPress, icon, variant = 'primary', disabled, loading, style }: { label: string; onPress: () => void; icon?: IconName; variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; disabled?: boolean; loading?: boolean; style?: StyleProp<ViewStyle> }) {
  const { colors } = useTheme();
  const foreground = variant === 'primary' ? colors.onPrimary : variant === 'danger' ? colors.danger : colors.primary;
  const background = variant === 'primary' ? colors.primary : variant === 'secondary' ? colors.primarySoft : 'transparent';
  return <Pressable accessibilityRole="button" accessibilityLabel={label} disabled={disabled || loading} onPress={onPress} style={({ pressed }) => [styles.button, { backgroundColor: background, borderColor: variant === 'danger' ? colors.danger : 'transparent', borderWidth: variant === 'danger' ? 1 : 0, opacity: disabled ? .45 : pressed ? .76 : 1 }, style]}>{loading ? <ActivityIndicator color={foreground} size="small" /> : icon ? <Ionicons name={icon} size={17} color={foreground} /> : null}<Text style={[styles.buttonText, { color: foreground }]}>{label}</Text></Pressable>;
}
export function IconButton({ icon, onPress, accessibilityLabel, disabled, size = 18 }: { icon: IconName; onPress: () => void; accessibilityLabel: string; disabled?: boolean; size?: number }) {
  const { colors } = useTheme();
  return <Pressable onPress={onPress} disabled={disabled} accessibilityLabel={accessibilityLabel} accessibilityRole="button" style={({ pressed }) => [styles.iconButton, { opacity: disabled ? .4 : pressed ? .6 : 1 }]}><Ionicons name={icon} size={size} color={colors.muted} /></Pressable>;
}
export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  const { colors } = useTheme();
  return <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }, style]}>{children}</View>;
}
export function SectionHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  const { colors } = useTheme();
  return <View style={styles.sectionHeader}><View style={{ flex: 1, gap: 5 }}><Text style={[styles.sectionTitle, { color: colors.text }]}>{title}</Text>{subtitle ? <Text style={[styles.description, { color: colors.muted }]}>{subtitle}</Text> : null}</View>{action}</View>;
}
export function ScreenHeader({ eyebrow, title, subtitle, right }: { eyebrow: string; title: string; subtitle?: string; right?: React.ReactNode }) {
  const { colors } = useTheme();
  return <View style={styles.screenHeader}><View style={{ flex: 1, gap: 9 }}><Text style={[styles.eyebrow, { color: colors.primary }]}>{eyebrow.toUpperCase()}</Text><Text style={[styles.screenTitle, { color: colors.text }]}>{title}</Text>{subtitle ? <Text style={[styles.description, { color: colors.muted, maxWidth: 620 }]}>{subtitle}</Text> : null}</View>{right}</View>;
}
export function Field({ label, value, onChangeText, placeholder, multiline, keyboardType, secureTextEntry, editable, style }: { label: string; value: string; onChangeText: (value: string) => void; placeholder?: string; multiline?: boolean; keyboardType?: KeyboardTypeOptions; secureTextEntry?: boolean; editable?: boolean; style?: StyleProp<ViewStyle> }) {
  const { colors } = useTheme();
  return <View style={[{ gap: 8, flex: 1 }, style]}><Text style={{ fontSize: 12, fontWeight: '600', color: colors.text }}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChangeText} placeholder={placeholder} placeholderTextColor={colors.muted} keyboardType={keyboardType} autoCapitalize={secureTextEntry || keyboardType === 'email-address' ? 'none' : 'sentences'} autoCorrect={!secureTextEntry && keyboardType !== 'email-address'} secureTextEntry={secureTextEntry} editable={editable} multiline={multiline} style={[styles.input, { color: colors.text, backgroundColor: colors.bg, borderColor: colors.border, minHeight: multiline ? 96 : 46, textAlignVertical: multiline ? 'top' : 'center' }]} /></View>;
}
export function Badge({ label, tone = 'neutral', icon }: { label: string; tone?: 'success' | 'warning' | 'danger' | 'neutral' | 'info'; icon?: IconName }) {
  const { colors } = useTheme();
  const color = tone === 'success' ? colors.primary : tone === 'warning' ? colors.warning : tone === 'danger' ? colors.danger : tone === 'info' ? colors.info : colors.muted;
  return <View style={[styles.badge, { backgroundColor: tone === 'neutral' ? colors.surfaceAlt : `${color}12` }]}>{icon ? <Ionicons name={icon} size={11} color={color} /> : null}<Text style={{ fontSize: 10, fontWeight: '600', color }}>{label}</Text></View>;
}
export function EmptyState({ icon, title, description, action }: { icon: IconName; title: string; description: string; action?: React.ReactNode }) {
  const { colors } = useTheme();
  return <View style={styles.empty}><View style={[styles.emptyIcon, { backgroundColor: colors.primarySoft }]}><Ionicons name={icon} size={25} color={colors.primary} /></View><Text style={[styles.sectionTitle, { color: colors.text, textAlign: 'center' }]}>{title}</Text><Text style={[styles.description, { color: colors.muted, textAlign: 'center', maxWidth: 320 }]}>{description}</Text>{action}</View>;
}
export function Divider() { const { colors } = useTheme(); return <View style={{ height: 1, backgroundColor: colors.border, marginVertical: 16 }} />; }
export function BrandMark({ size = 32 }: { size?: number }) { return <Image source={require('../../assets/brand/trabajo-ya-logo.jpg')} resizeMode="contain" accessibilityLabel="Logo de Trabajo YA" style={{ width: size, height: size, borderRadius: size * .18 }} />; }
export const textStyles = StyleSheet.create({ description: { fontSize: 13, lineHeight: 21 }, label: { fontSize: 11, fontWeight: '600', letterSpacing: .7, textTransform: 'uppercase' }, title: { fontSize: 17, fontWeight: '600', letterSpacing: -.3 } });
const styles = StyleSheet.create({
  button: { minHeight: 42, borderRadius: 10, paddingHorizontal: 17, paddingVertical: 11, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  buttonText: { fontSize: 12, fontWeight: '600' }, iconButton: { padding: 10, minWidth: 40, minHeight: 40, alignItems: 'center', justifyContent: 'center' },
  card: { borderWidth: 1, borderRadius: 18, padding: 22 }, sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 18 },
  sectionTitle: { fontSize: 17, fontWeight: '600', letterSpacing: -.35 }, description: { fontSize: 13, lineHeight: 21 },
  screenHeader: { marginBottom: 28, flexDirection: 'row', alignItems: 'center', gap: 14 }, eyebrow: { fontSize: 10, letterSpacing: 2, fontWeight: '700' },
  screenTitle: { fontSize: 32, fontWeight: '600', letterSpacing: -1.1, lineHeight: 39 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, fontSize: 13 },
  badge: { paddingVertical: 5, paddingHorizontal: 9, borderRadius: 6, flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start' },
  empty: { padding: 28, alignItems: 'center', gap: 12 }, emptyIcon: { width: 56, height: 56, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 4 },
});
