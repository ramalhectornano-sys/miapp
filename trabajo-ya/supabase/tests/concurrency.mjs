// Prueba opcional contra PostgreSQL/Supabase LOCAL con psql: sesiones reales
// compiten por el mismo presupuesto. No ejecuta fuentes ni proveedores de correo.
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

const connection = process.env.DATABASE_TEST_URL;
if (!connection) throw new Error('Definí DATABASE_TEST_URL para un Supabase local de pruebas.');
const parsed = new URL(connection);
if (!['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)) {
  throw new Error('Esta prueba solo admite localhost; no usar producción.');
}
const owner = randomUUID(); // UUID generado, nunca se interpolan datos externos en SQL.
function sql(statement) {
  return new Promise((resolve, reject) => {
    const processHandle = spawn('psql', ['-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1'], {
      env: { ...process.env, PGDATABASE: connection }, stdio: ['pipe', 'pipe', 'pipe'],
    });
    let output = ''; let errors = '';
    processHandle.stdout.on('data', chunk => { output += chunk; });
    processHandle.stderr.on('data', chunk => { errors += chunk; });
    processHandle.on('error', reject);
    processHandle.on('close', code => code === 0 ? resolve(output.trim()) : reject(new Error(errors.trim() || `psql terminó con ${code}`)));
    processHandle.stdin.end(statement);
  });
}
try {
  const setup = await sql(`
    begin;
    insert into auth.users(id) values ('${owner}');
    set local role service_role;
    do $$
    declare cv uuid:=gen_random_uuid(); account uuid:=gen_random_uuid();
      first_search uuid:=gen_random_uuid(); second_search uuid:=gen_random_uuid();
      search_key uuid; claim jsonb; job_key uuid; match_key uuid; application jsonb; counter integer;
    begin
      insert into public.resume_versions(id,user_id,name,original_filename,object_path,mime_type,size_bytes)
        values (cv,'${owner}','Fixture concurrencia','fixture.pdf','${owner}/fixture.pdf','application/pdf',100);
      insert into public.email_connections(id,user_id,provider,email,scopes)
        values (account,'${owner}','google','fixture@example.com',array['https://www.googleapis.com/auth/gmail.send']);
      insert into public.job_searches(id,user_id,name,roles,cities,timezone,next_run_at) values
        (first_search,'${owner}','Primera fixture',array['Chofer'],array['Neuquén'],'Pacific/Kiritimati',now()-interval '1 minute'),
        (second_search,'${owner}','Segunda fixture',array['Chofer'],array['Neuquén'],'Etc/GMT+12',now()-interval '1 minute');
      perform public.claim_search_now(first_search,'${owner}','concurrency-first');
      perform public.claim_search_now(second_search,'${owner}','concurrency-second');
      perform public.grant_sending_consent('${owner}',first_search,cv,account,array['authorized-feed'],now()+interval '30 days',
        'Autorizo los envíos automáticos de esta búsqueda');
      perform public.grant_sending_consent('${owner}',second_search,cv,account,array['authorized-feed'],now()+interval '30 days',
        'Autorizo los envíos automáticos de esta búsqueda');
      for counter in 1..24 loop
        search_key:=case when counter%2=0 then first_search else second_search end;
        job_key:=gen_random_uuid(); match_key:=gen_random_uuid();
        insert into public.jobs(id,user_id,source,fingerprint,company,title,city,recipient_email,recipient_verified_at,source_authorized)
          values (job_key,'${owner}','authorized-feed','fixture-'||counter,'Fixture','Chofer','Neuquén',
            'fixture-'||counter||'@example.com',now(),true);
        insert into public.job_search_matches(id,user_id,job_id,search_id,run_id,roles_snapshot,cities_snapshot)
          select match_key,'${owner}',job_key,search_key,r.id,array['Chofer'],array['Neuquén']
          from public.job_search_runs r join public.job_searches s on s.id=r.search_id and s.claim_token=r.claim_token
          where s.id=search_key and r.status='running';
        application:=public.create_initial_application(jsonb_build_object('user_id','${owner}','job_id',job_key,
          'search_id',search_key,'resume_id',cv,'email_connection_id',account,'company','Fixture','job_title','Chofer',
          'recipient_email','fixture-'||counter||'@example.com','recipient_verified_at',now(),
          'subject','SIN ENVÍO REAL: fixture','body','Prueba de reservas concurrentes','job_match_id',match_key));
      end loop;
    end; $$;
    select json_build_object('day',(now() at time zone 'America/Argentina/Buenos_Aires')::date,
      'applications',(select json_agg(id) from public.applications where user_id='${owner}'));
    commit;
  `);
  const fixture = JSON.parse(setup);
  const results = await Promise.all(fixture.applications.map((applicationId, index) => sql(`
    begin;
    set local role service_role;
    select public.claim_application_send('${applicationId}','${owner}',${index % 2 === 0},
      ${index % 2 === 0 ? "'Enviar esta postulación'" : 'null'}) is not null;
    commit;
  `)));
  const summary = JSON.parse(await sql(`select json_build_object(
    'day',(now() at time zone 'America/Argentina/Buenos_Aires')::date,
    'attempts',(select count(*) from public.applications where user_id='${owner}' and send_attempt_id is not null),
    'confirmed',(select count(*) from public.applications where user_id='${owner}' and provider_confirmed_at is not null));`));
  if (fixture.day !== summary.day) throw new Error('La prueba cruzó medianoche; volver a ejecutar para comparar el mismo día.');
  if (results.filter(result => result === 't').length !== 10 || Number(summary.attempts) !== 10 || Number(summary.confirmed) !== 0) {
    throw new Error('Falló la exclusión mutua: se esperan exactamente diez reservas y cero envíos confirmados.');
  }
  console.log('Concurrencia validada: 24 sesiones, 2 búsquedas, aprobaciones manuales y automáticas, exactamente 10 reservas. Cero correos enviados.');
} finally {
  await sql(`delete from auth.users where id='${owner}';`);
}
