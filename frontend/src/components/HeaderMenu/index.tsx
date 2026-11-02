'use client';

import { usePathname } from 'next/navigation';
import {
  Anchor,
  Badge,
  Burger,
  Container,
  Drawer,
  Group,
  Image,
  Menu,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import classes from './HeaderMenu.module.css';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ProfileModal } from '../profile/SetProfile';
import { COLORS, FONTS } from '@/app/theme';
import { GithubLogoIcon } from '@phosphor-icons/react';
import { useChatStatus } from '../Chat/useChatStatus';

type SubLink = {
  link: string;
  label: string;
  icon?: React.ElementType;
  external?: boolean;
  disabled?: boolean;
};
type NavGroup = { label: string; links: SubLink[] };
type NavItem = {
  link: string;
  label: string;
  links?: SubLink[];
  groups?: NavGroup[];
};

const links: NavItem[] = [
  { link: '/', label: 'Home' },
  { link: '/mapping', label: 'Map' },
  {
    link: '/data-viewer',
    label: 'Data',
    groups: [
      {
        label: 'Explore',
        links: [
          { link: '/data-viewer', label: 'Data Gallery' },
          {
            link: '/data-comparison/variable-explorer',
            label: 'Variable Relationship Map',
          },
        ],
      },
      {
        label: 'Compare',
        links: [
          {
            link: '/data-comparison/dp-explorer',
            label: 'Census Variable Comparison',
          },
          {
            link: '/data-comparison/county-comparison',
            label: 'Statewide County Comparison',
          },
          // Legacy page (CDC only version of the variable relationship map)
          // {
          //   link: '/data-comparison/variable-comparison',
          //   label: 'CDC Health Map',
          // },
        ],
      },
      {
        label: 'Reports',
        links: [
          {
            link: '/data-comparison/reports-by-topic',
            label: 'Reports by Topic',
          },
          { link: '/working-report', label: 'Working Report' },
        ],
      },
      {
        label: 'Export',
        links: [{ link: '/data-export', label: 'Data Export' }],
      },
    ],
  },
  {
    link: '/resources',
    label: 'Resources',
    links: [
      { link: '/resources/data-sources', label: 'Data Sources ' },
      //{ link: '/resources/benefits-estimator', label: 'Benefits Estimator' },
      { link: '/resources/white-papers', label: 'White Papers' },
      { link: '/resources/announcements', label: 'Announcements' },
      { link: '/resources/tutorials', label: 'Tutorials' },
      {
        link: 'https://github.com/VERSO-UVM/react-vt-data',
        label: 'GitHub',
        icon: GithubLogoIcon,
        external: true,
      },
    ],
  },
  {
    link: '/about',
    label: 'About',
    links: [
      { link: '/about/team', label: 'Our Team' },
      { link: '/about/contact', label: 'Contact Us' },
    ],
  },
];

function SubLinkMenuItem({ item }: { item: SubLink }) {
  const Icon = item.icon;

  if (item.disabled) {
    return (
      <Menu.Item
        disabled
        rightSection={
          <span
            style={{
              fontFamily: FONTS.mono,
              fontSize: 10,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: COLORS.slate,
            }}
          >
            Soon
          </span>
        }
        leftSection={Icon ? <Icon size={16} /> : undefined}
      >
        {item.label}
      </Menu.Item>
    );
  }

  if (item.external) {
    return (
      <Menu.Item
        component="a"
        href={item.link}
        target="_blank"
        rel="noopener noreferrer"
        leftSection={Icon ? <Icon size={16} /> : undefined}
      >
        {item.label}
      </Menu.Item>
    );
  }

  return (
    <Menu.Item
      component={Link}
      href={item.link}
      leftSection={Icon ? <Icon size={16} /> : undefined}
    >
      {item.label}
    </Menu.Item>
  );
}

const isCurrent = (pathname: string, link: string) =>
  pathname === link || pathname.startsWith(link + '/');

/** The nav for narrow screens, where the header's links are hidden: every
 *  section and its pages in one list. */
function MobileNav({
  links,
  pathname,
  onNavigate,
}: {
  links: NavItem[];
  pathname: string;
  onNavigate: () => void;
}) {
  const item = (sub: SubLink) => {
    if (sub.disabled) return null;
    const Icon = sub.icon;
    const content = (
      <>
        {Icon && <Icon size={16} />}
        {sub.label}
      </>
    );
    return sub.external ? (
      <a
        key={sub.link}
        href={sub.link}
        target="_blank"
        rel="noopener noreferrer"
        className={classes.drawerLink}
      >
        {content}
      </a>
    ) : (
      <Link
        key={sub.link}
        href={sub.link}
        onClick={onNavigate}
        className={`${classes.drawerLink} ${
          isCurrent(pathname, sub.link) ? classes.drawerLinkActive : ''
        }`}
      >
        {content}
      </Link>
    );
  };

  return (
    <nav className={classes.drawerNav}>
      {links.map((link) => {
        const subLinks =
          link.links ?? link.groups?.flatMap((group) => group.links);
        if (!subLinks) return item(link);
        return (
          <div key={link.label} className={classes.drawerSection}>
            <span className={classes.drawerSectionLabel}>{link.label}</span>
            {subLinks.map(item)}
          </div>
        );
      })}
    </nav>
  );
}

export default function HeaderMenu() {
  const pathname = usePathname(); /* Get the current pathname */

  const [opened, { toggle, close }] = useDisclosure(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let lastY = window.scrollY;

    const onScroll = () => {
      const currentY = window.scrollY;

      // Don't hide while near the top
      if (currentY < 80) {
        setHidden(false);
      } else if (currentY > lastY) {
        // Scrolling down
        setHidden(true);
      } else {
        // Scrolling up
        setHidden(false);
      }

      lastY = currentY;
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Data Chat sits after Data, only when the backend has CHAT_ENABLED set.
  const chatEnabled = useChatStatus()?.enabled ?? false;
  const navLinks: NavItem[] = chatEnabled
    ? [...links.slice(0, 3), { link: '/chat', label: 'Ask' }, ...links.slice(3)]
    : links;

  const items = navLinks.map((link) => {
    const subRoutes: SubLink[] =
      link.links ?? link.groups?.flatMap((group) => group.links) ?? [];

    const active =
      pathname === link.link ||
      pathname.startsWith(link.link + '/') ||
      subRoutes.some(
        (sub) => pathname === sub.link || pathname.startsWith(sub.link + '/'),
      );

    const flatItems = link.links?.map((item) => (
      <SubLinkMenuItem key={item.link} item={item} />
    ));

    const groupedItems = link.groups?.flatMap((group, groupIndex) => {
      const groupContent = [
        <Menu.Label key={`${link.label}-${group.label}-label`}>
          {group.label}
        </Menu.Label>,
        ...group.links.map((item) => (
          <SubLinkMenuItem key={item.link} item={item} />
        )),
      ];

      if (groupIndex < (link.groups?.length ?? 0) - 1) {
        groupContent.push(
          <Menu.Divider key={`${link.label}-${group.label}-divider`} />,
        );
      }

      return groupContent;
    });

    const menuItems = flatItems ?? groupedItems;

    if (menuItems) {
      return (
        <Menu
          key={link.label}
          trigger="hover"
          shadow="xl"
          radius={0}
          offset={10}
          transitionProps={{
            transition: 'pop-top-left',
            duration: 150,
          }}
          withinPortal
        >
          <Menu.Target>
            <Link
              href={link.link}
              className={`${classes.link} ${active ? classes.active : ''}`}
            >
              <span className={classes.linkLabel}>{link.label}</span>
            </Link>
          </Menu.Target>
          <Menu.Dropdown>{menuItems}</Menu.Dropdown>
        </Menu>
      );
    }
    return (
      <Link
        href={link.link}
        key={link.link}
        className={`${classes.link} ${active ? classes.active : ''}`}
      >
        <span className={classes.linkLabel}>{link.label}</span>
      </Link>
    );
  });

  return (
    <header
      className={`${classes.header} ${hidden ? classes.hidden : ''}`}
      data-hidden={hidden}
    >
      <Container size="xl">
        <div className={classes.inner}>
          <Group gap="lg" wrap="nowrap">
            <Anchor href="/">
              <Image
                src="/images/VDC_logo.webp"
                alt="Logo"
                w={140}
                h={50}
                style={{ cursor: 'pointer' }}
              />
            </Anchor>
            <Badge
              visibleFrom="xs"
              style={{
                color: COLORS.spruceDeep,
                background: COLORS.amber,
                fontFamily: FONTS.mono,
              }}
            >
              Beta
            </Badge>
          </Group>

          {/* Navigation items separated into their own wrapping group */}
          <Group
            gap={4}
            visibleFrom="md"
            wrap="wrap"
            style={{ flex: 1, justifyContent: 'flex-end' }}
          >
            {items}
          </Group>
          {/* Grouped so the button stays at the right edge when the nav
              links are hidden on narrow screens. */}
          <Group gap="sm" wrap="nowrap">
            <ProfileModal />
            <Burger
              opened={opened}
              onClick={toggle}
              size="sm"
              hiddenFrom="md"
              aria-label={opened ? 'Close menu' : 'Open menu'}
            />
          </Group>
        </div>
      </Container>

      <Drawer
        opened={opened}
        onClose={close}
        position="right"
        size={300}
        title="Menu"
        hiddenFrom="md"
        // Above the sticky header (z-index 1000) and its menus.
        zIndex={1100}
      >
        <MobileNav links={navLinks} pathname={pathname} onNavigate={close} />
      </Drawer>
    </header>
  );
}
