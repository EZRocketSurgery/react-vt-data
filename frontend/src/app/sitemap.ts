import type { MetadataRoute } from 'next';

const siteUrl = 'https://vtdatacollab.uvm.edu';

export const dynamic = 'force-static';

const PATHS = ['', '/data-viewer', '/mapping', '/resources', '/about'];

export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({
    url: `${siteUrl}${path}`,
    lastModified: new Date(),
    changeFrequency: 'monthly',
    priority: path === '' ? 1 : 0.8,
  }));
}
