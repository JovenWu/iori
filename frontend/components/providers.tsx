"use client"

import { TooltipProvider } from "@/components/ui/tooltip"
import { AuthProvider } from "@/lib/auth"
import { SettingsProvider } from "@/lib/settings"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <SettingsProvider>
        <TooltipProvider>{children}</TooltipProvider>
      </SettingsProvider>
    </AuthProvider>
  )
}
