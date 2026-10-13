import type { AppState, JobSearch, SearchProposal } from '../types';

export function initialDemoState(): AppState {
  return {
    profile: { full_name: 'Martín Pérez', city: 'Rincón de los Sauces', headline: 'Perfil de ejemplo: chofer con experiencia en transporte y logística.', photo_path: null,
      experiences: [{ id: 'demo-exp', company: 'Transportes del Sur · Ejemplo', role: 'Chofer', description: 'Experiencia ficticia para explorar la aplicación.', start_date: '2022-01-01' }],
      credentials: [{ id: 'demo-course', name: 'Licencia profesional · Ejemplo', issuer: 'Datos ficticios', kind: 'license' }], references: [] },
    resumes: [{ id: 'demo-resume', name: 'CV de chofer · Demostración', file_name: 'curriculum_ejemplo.pdf', storage_path: '', mime_type: 'application/pdf', size_bytes: 0, created_at: '2026-10-12T12:00:00Z', is_default: true, demo: true }],
    searches: [{ id: 'demo-search', name: 'Chofer en Rincón de los Sauces', roles: ['Chofer'], cities: ['Rincón de los Sauces'], schedule_time: '09:00:00', timezone: 'America/Argentina/Buenos_Aires', frequency: 'daily', weekdays: [1,2,3,4,5,6,7], status: 'enabled', auto_apply: false, next_run_at: null, last_run_at: null, preferred_resume_id: 'demo-resume', demo: true }],
    applications: [{ id: 'demo-application', company: 'Transportes del Sur · Ejemplo', role: 'Chofer', recipient_email: 'seleccion@example.com', subject: 'Postulación de ejemplo — Chofer', body: 'Hola, equipo de selección:\n\nEste es un borrador ficticio para mostrar el panel de postulaciones de Trabajo YA. No corresponde a una vacante real ni se envió por correo.\n\nSaludos,\nMartín Pérez · Perfil de demostración', resume_id: 'demo-resume', status: 'pending', created_at: '2026-10-12T12:00:00Z', provider_message_id: null, provider_confirmed_at: null, demo: true }],
    messages: [{ id: 'demo-welcome', role: 'assistant', content: 'Estoy acá para ayudarte a encontrar tu próximo trabajo. Contame qué puesto buscás, en qué ciudad y a qué hora querés buscar. Esta es una demostración: no se ejecutan búsquedas ni se envían correos.', created_at: '2026-10-12T12:00:00Z', demo: true }],
  };
}

export function demoSearch(proposal: SearchProposal): JobSearch {
  return { id: `demo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, name: proposal.title, roles: [proposal.role], cities: [proposal.city], schedule_time: proposal.time, timezone: proposal.timezone, frequency: proposal.frequency, weekdays: [...proposal.weekdays], status: 'enabled', auto_apply: false, next_run_at: null, last_run_at: null, preferred_resume_id: proposal.resume_id || null, demo: true };
}

export function demoChat(message: string): { reply: string; proposal?: SearchProposal } {
  const roleMatch = /(?:empleos?|trabajos?|puestos?|vacantes?)\s+(?:de |como |para )?(.+?)\s+en\s+/i.exec(message);
  if (!roleMatch) return { reply: 'Modo demostración: puedo preparar una configuración con los datos que escribas. Por ejemplo: “Buscá empleos de chofer en Rincón de los Sauces todos los días a las 9”. Para analizar tu CV necesitás conectar el backend; no inventaré información de tu perfil.' };
  const city = message.slice((roleMatch.index || 0) + roleMatch[0].length).split(/\s+(?:todos?\b|cada\b|a las\b|los\s+(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bados?|domingos?)\b|y envi|envi|diariamente\b)|[.!?\n]/i)[0]?.trim();
  const role = roleMatch[1]?.trim();
  const normalized = message.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const clock = /a las?\s+(\d{1,2})(?::(\d{2}))?/.exec(normalized);
  if (!role || !city || !clock) return { reply: 'Indicá el puesto, la ciudad y un horario, por ejemplo “a las 9”. No se guardó ni ejecutó ninguna búsqueda.' };
  let hour = Number(clock[1]);
  const minute = Number(clock[2] || 0);
  if (/(tarde|noche|pm)\b/.test(normalized) && hour < 12) hour += 12;
  if (hour > 23 || minute > 59) return { reply: 'Revisá el horario: debe estar entre 00:00 y 23:59. No se guardó la búsqueda.' };
  const days = ['lunes','martes','miercoles','jueves','viernes','sabado','domingo'].flatMap((day,index) => normalized.includes(day) ? [index+1] : []);
  const weekly = days.length > 0 || normalized.includes('seman');
  if (weekly && !days.length) return { reply: 'Para una búsqueda semanal, indicá qué día o días preferís. No se guardó ni ejecutó ninguna búsqueda.' };
  const proposal: SearchProposal = { title: `${role} en ${city}`, role, city, time: `${String(hour).padStart(2,'0')}:${String(minute).padStart(2,'0')}`, frequency: weekly ? 'weekly' : 'daily', weekdays: weekly ? days : [1,2,3,4,5,6,7], timezone: 'America/Argentina/Buenos_Aires', mode: /(?:envia|manda|postula)/.test(normalized) ? 'automatic' : 'manual' };
  return { proposal, reply: `Preparé una propuesta de demostración para ${role} en ${city}. Revisala y confirmá para guardarla en esta sesión. No se ejecutó ninguna búsqueda ni se enviaron correos.` };
}
