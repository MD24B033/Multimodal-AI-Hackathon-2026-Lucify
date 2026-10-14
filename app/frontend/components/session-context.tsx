"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  authRequired,
  get,
  post,
  readAccessKey,
  setUnauthorizedHandler,
  signIn,
  writeAccessKey,
} from "@/lib/api";
import type { Course, Profile, Student } from "@/lib/types";

type SessionValue = {
  ready: boolean;
  authRequired: boolean;
  signedIn: boolean;
  student: Student | null;
  profiles: Profile[];
  profile: Profile | null;
  selectProfile: (id: string) => void;
  refreshProfiles: () => Promise<void>;
  courses: Course[];
  loadingCourses: boolean;
  error: string | null;
  theme: "dark" | "light";
  signInWithKey: (key: string) => Promise<void>;
  signOut: () => void;
  refreshCourses: () => Promise<void>;
  toggleTheme: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);
const THEME_KEY = "companion.theme";
const PROFILE_KEY = "companion.profile";

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [required, setRequired] = useState(false);
  const [student, setStudent] = useState<Student | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loadingCourses, setLoadingCourses] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(THEME_KEY);
    } catch {
      stored = null;
    }
    const next = stored === "light" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        window.localStorage.setItem(THEME_KEY, next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const signOut = useCallback(() => {
    writeAccessKey(null);
    setStudent(null);
    setCourses([]);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      writeAccessKey(null);
      setStudent(null);
      router.replace("/login");
    });
    return () => setUnauthorizedHandler(null);
  }, [router]);

  const refreshProfiles = useCallback(async () => {
    try {
      const list = await get<Profile[]>("/api/profiles");
      setProfiles(list);
      setProfileId((current) => {
        if (current && list.some((item) => item.id === current)) return current;
        let stored: string | null = null;
        try {
          stored = window.localStorage.getItem(PROFILE_KEY);
        } catch {
          stored = null;
        }
        if (stored && list.some((item) => item.id === stored)) return stored;
        return list[0]?.id ?? null;
      });
    } catch {
      setProfiles([]);
    }
  }, []);

  const refreshCourses = useCallback(async () => {
    setLoadingCourses(true);
    try {
      const query = profileId ? `?profile_id=${profileId}` : "";
      setCourses(await get<Course[]>(`/api/courses${query}`));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reach the API");
    } finally {
      setLoadingCourses(false);
    }
  }, [profileId]);

  const selectProfile = useCallback((id: string) => {
    setProfileId(id);
    try {
      window.localStorage.setItem(PROFILE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (profileId) void refreshCourses();
  }, [profileId, refreshCourses]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      const needsAuth = await authRequired();
      if (cancelled) return;
      setRequired(needsAuth);

      if (!needsAuth) {
        const students = await get<Student[]>("/api/learner/students").catch(() => []);
        if (cancelled) return;
        setStudent(students[0] ?? null);
        await refreshProfiles();
        if (!cancelled) setReady(true);
        return;
      }

      if (!readAccessKey()) {
        if (!cancelled) setReady(true);
        return;
      }

      try {
        const me = await get<{ student: Student | null }>("/api/auth/me");
        if (cancelled) return;
        setStudent(me.student);
        await refreshProfiles();
      } catch {
        if (!cancelled) setStudent(null);
      } finally {
        if (!cancelled) setReady(true);
      }
    }

    void boot();
    return () => {
      cancelled = true;
    };
  }, [refreshProfiles]);

  const signInWithKey = useCallback(
    async (key: string) => {
      const result = await signIn(key.trim());
      writeAccessKey(key.trim());
      setStudent(result.student as Student);
      await refreshProfiles();
    },
    [refreshProfiles],
  );

  const value = useMemo<SessionValue>(
    () => ({
      ready,
      authRequired: required,
      signedIn: !required || student !== null,
      student,
      profiles,
      profile: profiles.find((item) => item.id === profileId) ?? null,
      selectProfile,
      refreshProfiles,
      courses,
      loadingCourses,
      error,
      theme,
      signInWithKey,
      signOut,
      refreshCourses,
      toggleTheme,
    }),
    [
      ready,
      required,
      student,
      profiles,
      profileId,
      selectProfile,
      refreshProfiles,
      courses,
      loadingCourses,
      error,
      theme,
      signInWithKey,
      signOut,
      refreshCourses,
      toggleTheme,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return value;
}

export async function createCourse(payload: {
  profile_id?: string | null;
  title: string;
  description?: string | null;
  exam_date?: string | null;
  weekly_hours?: number | null;
  difficulty?: string | null;
  goal?: string | null;
}): Promise<Course> {
  return post<Course>("/api/courses", payload);
}
