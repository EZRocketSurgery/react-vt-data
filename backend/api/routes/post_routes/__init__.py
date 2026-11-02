from .post_acs5_db import router as post_acs5_router
from .post_ambulance import router as post_ambulance_router
from .post_cdc import router as post_cdc_router
from .post_comparison import router as post_comparison_router
from .post_export import router as post_export_router
from .post_flood import router as post_flood_router
from .post_parcels import router as post_parcels_router
from .post_qcew import router as post_qcew_router
from .post_wastewater import router as post_wastewater_router
from .post_zoning import router as post_zoning_router

all_post_routers = [
    post_zoning_router,
    post_acs5_router,
    post_qcew_router,
    post_wastewater_router,
    post_export_router,
    post_cdc_router,
    post_comparison_router,
    post_ambulance_router,
    post_parcels_router,
    post_flood_router,
]
