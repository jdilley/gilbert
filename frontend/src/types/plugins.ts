export interface InstalledPlugin {
  name: string;
  version: string;
  description: string;
  install_path: string;
  source: "std" | "local" | "installed" | "unknown" | string;
  source_url: string | null;
  installed_at: string | null;
  registered_services: string[];
  running: boolean;
  uninstallable: boolean;
}

export interface InstallPluginResponse {
  plugin: InstalledPlugin;
}
