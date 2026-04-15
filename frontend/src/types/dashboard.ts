export interface DashboardCard {
  title: string;
  description: string;
  url: string;
  icon: string;
  required_role: string;
}

export interface NavItem {
  label: string;
  description: string;
  url: string;
  icon: string;
  required_role: string;
}

export interface NavGroup {
  key: string;
  label: string;
  description: string;
  url: string;
  icon: string;
  items: NavItem[];
}

export interface DashboardResponse {
  cards: DashboardCard[];
  nav: NavGroup[];
}
