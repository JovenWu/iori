"use client"

import { useState } from "react"
import {
  BellIcon,
  BrainIcon,
  CheckIcon,
  ChevronsUpDownIcon,
  CircleUserRoundIcon,
  LogOutIcon,
  MonitorIcon,
  MoonIcon,
  PaletteIcon,
  SlidersHorizontalIcon,
  SunIcon,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Avatar,
  AvatarFallback,
} from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"
import { useSettings, type LanguagePreference, type ThemePreference } from "@/lib/settings"

type SettingsSection =
  | "general"
  | "appearance"
  | "notifications"
  | "memory"
  | "account"

const SECTIONS: {
  id: SettingsSection
  label: string
  icon: React.ComponentType<{ className?: string }>
}[] = [
  { id: "general", label: "General", icon: SlidersHorizontalIcon },
  { id: "appearance", label: "Appearance", icon: PaletteIcon },
  { id: "notifications", label: "Notifications", icon: BellIcon },
  { id: "memory", label: "Memory", icon: BrainIcon },
  { id: "account", label: "Account", icon: CircleUserRoundIcon },
]

const SECTION_TITLES: Record<SettingsSection, string> = {
  general: "General",
  appearance: "Appearance",
  notifications: "Notifications",
  memory: "Memory",
  account: "Account",
}

const THEME_OPTIONS: {
  value: ThemePreference
  label: string
  icon: React.ComponentType<{ className?: string }>
}[] = [
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
  { value: "system", label: "System", icon: MonitorIcon },
]

const LANGUAGES: { value: LanguagePreference; label: string }[] = [
  { value: "en", label: "English" },
  { value: "id", label: "Indonesia" },
]

function SettingRow({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-6 py-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description && (
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function ThemeSegmentedControl() {
  const { settings, updateSettings } = useSettings()

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5"
    >
      {THEME_OPTIONS.map((option) => {
        const active = settings.theme === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => updateSettings({ theme: option.value })}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <option.icon className="size-3.5" />
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

function LanguageSelect() {
  const { settings, updateSettings } = useSettings()
  const [open, setOpen] = useState(false)
  const selected = LANGUAGES.find((l) => l.value === settings.language)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-36 justify-between font-normal"
        >
          {selected?.label ?? "English"}
          <ChevronsUpDownIcon className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-36 p-0">
        <Command>
          <CommandList>
            <CommandGroup>
              {LANGUAGES.map((language) => (
                <CommandItem
                  key={language.value}
                  value={language.value}
                  onSelect={(value) => {
                    updateSettings({ language: value as LanguagePreference })
                    setOpen(false)
                  }}
                >
                  {language.label}
                  <CheckIcon
                    className={cn(
                      "ml-auto size-4",
                      settings.language === language.value
                        ? "opacity-100"
                        : "opacity-0",
                    )}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function BrowserNotificationsSwitch() {
  const supported =
    typeof window !== "undefined" && "Notification" in window
  const [granted, setGranted] = useState(
    () => supported && Notification.permission === "granted",
  )

  return (
    <Switch
      checked={granted}
      disabled={!supported}
      aria-label="Browser notifications"
      onCheckedChange={(checked) => {
        if (!checked) {
          // Browsers don't allow revoking programmatically; the setting just
          // reflects the permission state.
          return
        }
        void Notification.requestPermission().then((permission) => {
          setGranted(permission === "granted")
        })
      }}
    />
  )
}

interface SettingsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Opens the memory manager on top of this dialog. */
  onOpenMemory?: () => void
}

export function SettingsModal({
  open,
  onOpenChange,
  onOpenMemory,
}: SettingsModalProps) {
  const { user, logout } = useAuth()
  const { settings, updateSettings } = useSettings()
  const [section, setSection] = useState<SettingsSection>("general")

  const displayName = user?.name ?? user?.username ?? "User"
  const initials =
    displayName
      .split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2) || "U"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="h-[min(34rem,calc(100vh-2rem))] w-[min(44rem,calc(100vw-2rem))] gap-0 overflow-hidden p-0 sm:max-w-none"
        showCloseButton
      >
        <DialogHeader className="sr-only">
          <DialogTitle>Settings</DialogTitle>
        </DialogHeader>

        <div className="flex h-full min-h-0 flex-col md:grid md:grid-cols-[12rem_minmax(0,1fr)]">
          {/* Section nav */}
          <nav
            aria-label="Settings sections"
            className="shrink-0 border-b border-border/60 bg-muted/40 p-2 md:border-b-0 md:border-r"
          >
            <p className="hidden px-2 pb-2 pt-3 text-sm font-semibold md:block">
              Settings
            </p>
            <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
              {SECTIONS.map((item) => {
                const active = section === item.id
                return (
                  <li key={item.id} className="shrink-0">
                    <button
                      type="button"
                      onClick={() => setSection(item.id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "flex w-full cursor-pointer items-center gap-2 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm transition-colors",
                        active
                          ? "bg-accent font-medium text-accent-foreground"
                          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                      )}
                    >
                      <item.icon className="size-4" />
                      {item.label}
                    </button>
                  </li>
                )
              })}
            </ul>
          </nav>

          {/* Section content */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <h2 className="px-6 pb-1 pt-5 text-base font-semibold">
              {SECTION_TITLES[section]}
            </h2>
            <div className="divide-y divide-border/60 px-6 pb-6">
              {section === "general" && (
                <>
                  <SettingRow
                    title="Language"
                    description="Assistant replies and the Corporate Actions page use this language."
                  >
                    <LanguageSelect />
                  </SettingRow>
                  <SettingRow
                    title="Send messages with Enter"
                    description="When off, press Ctrl+Enter to send and Enter adds a new line."
                  >
                    <Switch
                      checked={settings.sendWithEnter}
                      onCheckedChange={(checked) =>
                        updateSettings({ sendWithEnter: checked })
                      }
                      aria-label="Send messages with Enter"
                    />
                  </SettingRow>
                </>
              )}

              {section === "appearance" && (
                <SettingRow
                  title="Theme"
                  description="System follows your device's appearance setting."
                >
                  <ThemeSegmentedControl />
                </SettingRow>
              )}

              {section === "notifications" && (
                <>
                  <SettingRow
                    title="Response ready alerts"
                    description="Show a notification when a chat you left finishes generating."
                  >
                    <Switch
                      checked={settings.notifyOnDone}
                      onCheckedChange={(checked) =>
                        updateSettings({ notifyOnDone: checked })
                      }
                      aria-label="Response ready alerts"
                    />
                  </SettingRow>
                  <SettingRow
                    title="Browser notifications"
                    description="Allow this device to show system notifications."
                  >
                    <BrowserNotificationsSwitch />
                  </SettingRow>
                </>
              )}

              {section === "memory" && (
                <>
                  <SettingRow
                    title="Remember across chats"
                    description="Let the assistant keep helpful details between conversations."
                  >
                    <Switch
                      checked={settings.memoryEnabled}
                      onCheckedChange={(checked) =>
                        updateSettings({ memoryEnabled: checked })
                      }
                      aria-label="Remember across chats"
                    />
                  </SettingRow>
                  <SettingRow
                    title="Saved memories"
                    description="Review and delete what the assistant has remembered."
                  >
                    <Button variant="outline" onClick={onOpenMemory}>
                      Manage memories
                    </Button>
                  </SettingRow>
                </>
              )}

              {section === "account" && (
                <>
                  <div className="flex items-center gap-3 py-4">
                    <Avatar className="size-10 rounded-lg">
                      <AvatarFallback className="rounded-lg">
                        {initials}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {displayName}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {user?.username ? `@${user.username}` : ""}
                      </p>
                    </div>
                  </div>
                  <SettingRow
                    title="Log out"
                    description="Sign out of Sectors Agent on this device."
                  >
                    <Button variant="outline" onClick={logout}>
                      <LogOutIcon className="size-4" />
                      Log out
                    </Button>
                  </SettingRow>
                </>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
