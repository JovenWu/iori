"use client";

import { create } from "zustand";
import {
  createSchedule,
  deleteSchedule,
  getAccessToken,
  listSchedules,
  runScheduleNow,
  updateSchedule,
  type ScheduleInput,
  type ScheduleJob,
} from "@/lib/api";

interface SchedulesStore {
  jobs: ScheduleJob[];
  /** False until the first listSchedules fetch resolves. */
  loaded: boolean;
  refresh: () => Promise<void>;
  create: (input: ScheduleInput) => Promise<void>;
  update: (
    id: string,
    patch: Partial<ScheduleInput & { enabled: boolean }>,
  ) => Promise<void>;
  remove: (id: string) => Promise<void>;
  /** Optimistic toggle — rolls back on failure. */
  toggle: (job: ScheduleJob, enabled: boolean) => Promise<void>;
  /** Fire the job immediately; resolves to "fired" | "skipped" | "busy". */
  runNow: (job: ScheduleJob) => Promise<string>;
}

export const useSchedulesStore = create<SchedulesStore>()((set, get) => ({
  jobs: [],
  loaded: false,

  refresh: async () => {
    if (!getAccessToken()) return;
    try {
      set({ jobs: await listSchedules(), loaded: true });
    } catch (err) {
      console.error("Failed to fetch schedules:", err);
      set({ loaded: true });
    }
  },

  create: async (input) => {
    await createSchedule(input);
    await get().refresh();
  },

  update: async (id, patch) => {
    await updateSchedule(id, patch);
    await get().refresh();
  },

  remove: async (id) => {
    await deleteSchedule(id);
    await get().refresh();
  },

  toggle: async (job, enabled) => {
    set((s) => ({
      jobs: s.jobs.map((j) => (j.id === job.id ? { ...j, enabled } : j)),
    }));
    try {
      await updateSchedule(job.id, { enabled });
    } catch (err) {
      set((s) => ({
        jobs: s.jobs.map((j) => (j.id === job.id ? job : j)),
      }));
      throw err;
    }
  },

  runNow: async (job) => {
    const { status } = await runScheduleNow(job.id);
    await get().refresh();
    return status;
  },
}));

/** Drop state on logout — a second session must not see stale jobs. */
export function resetSchedulesStore() {
  useSchedulesStore.setState({ jobs: [], loaded: false });
}
