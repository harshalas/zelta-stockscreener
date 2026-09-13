import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// We deliberately don't throw here. Netlify/Vercel preview builds and the
// Next.js production build both evaluate this module even when env vars
// haven't been configured yet (e.g. before the user has created their
// Supabase project). Throwing at import time would crash the whole app;
// instead `useAuth` surfaces a clear "not configured" state in the UI, and
// getSupabaseClient() below throws only when something actually tries to
// use it without config.
let client: ReturnType<typeof createClient> | null = null;

if (supabaseUrl && supabaseAnonKey) {
  client = createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
    },
  });
}

export const supabase = client;

export function isSupabaseConfigured(): boolean {
  return client !== null;
}

export function getSupabaseClient() {
  if (!client) {
    throw new Error(
      "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and " +
        "NEXT_PUBLIC_SUPABASE_ANON_KEY in your environment."
    );
  }
  return client;
}
