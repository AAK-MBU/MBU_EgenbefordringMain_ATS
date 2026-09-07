"""Module to handle process finalization"""
# from mbu_rpa_core.exceptions import ProcessError, BusinessError

import os
import logging

from io import BytesIO

import pandas as pd

from mbu_msoffice_integration.sharepoint_class import Sharepoint

from helpers import ats_functions, config, helper_functions

logger = logging.getLogger(__name__)

COLUMNS = [
    "barnets_navn",
    "cpr_nummer_barn",
    "barnets_adresse",
    "kunne_du_ikke_finde_skole_eller_dagtilbud_paa_listen_",
    "skoleliste",
    "skriv_dit_barns_skole_eller_dagtilbud",
    "barn_distance_til_skole_api",
    "beloebsmodtager_navn_mitid",
    "cpr_beloebsmodtager_mitid",
    "anden_beloebsmodtager_navn_manuelt",
    "cpr_anden_beloebsmodtager_manuelt",
    "total_km_beregnet",
    "beloeb_i_alt",
    "aendret_beloeb_i_alt",
    "modtagelsesdato",
    "godkendt",
    "godkendt_af",
    "behandlet_ok",
    "behandlet_fejl",
    "jeg_erklaerer_paa_tro_og_love_at_de_oplysninger_jeg_har_givet_er",
    "jeg_er_indforstaaet_med_at_aarhus_kommune_behandler_angivne_oply",
    "evt_kommentar",
    "koerselsliste",
    "attachments",
    "uuid",
]


def finalize_process(current_run_file_name: str):
    """Function to handle process finalization"""

    logger.info("Running finalize_process()")

    excel_rows = []

    failed_work_items = False

    all_runs_completed_or_failed = True

    folder_dest = "Behandlet"

    current_run_workqueue_items = ats_functions.fetch_run_workqueue_items(file_name=current_run_file_name)

    for run in current_run_workqueue_items:
        if run.get("status") == "new":
            all_runs_completed_or_failed = False

        elif run.get("status") in ("failed", "pending user action"):
            failed_work_items = True

            folder_dest = "Fejlet"

        excel_rows.append(run["data"]["item"]["data"]["raw_excel_data"])

    if all_runs_completed_or_failed:
        logger.info("All runs done with either completed or failed status")

        update_sharepoint(excel_rows=excel_rows, file_name=current_run_file_name, folder_dest=folder_dest, failed_work_items=failed_work_items)

        helper_functions.send_mail(failed_work_items=failed_work_items)

    else:
        logger.info("All runs are yet to be completed or failed")


def update_sharepoint(excel_rows: list, file_name: str, folder_dest: str, failed_work_items: bool):
    """Update the SharePoint folders."""

    logger.info("Updating SharePoint folders.")

    sharepoint = Sharepoint(**config.SHAREPOINT_KWARGS)

    df = pd.DataFrame(excel_rows)
    df = helper_functions.ensure_columns(df=df, column_order=COLUMNS)

    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    buffer.seek(0)
    bytes_data = buffer.read()

    sharepoint.upload_file_from_bytes(binary_content=bytes_data, file_name=file_name, folder_name=f"{config.FOLDER_NAME}/{folder_dest}")

    logger.info(f"Excel file uploaded to the {folder_dest} folder")

    if failed_work_items:
        receipt_folder_name = os.path.splitext(file_name)[0]

        upload_folder_to_sharepoint(folder_dest=folder_dest, receipt_folder_name=receipt_folder_name, sharepoint=sharepoint)

    delete_file_from_sharepoint(file_name=file_name, sharepoint=sharepoint)


def upload_folder_to_sharepoint(folder_dest: str, receipt_folder_name: str, sharepoint: Sharepoint) -> None:
    """Upload a folder and its contents to SharePoint."""

    target_folder_url = "/".join(
        [
            config.DOCUMENT_LIBRARY,
            config.FOLDER_NAME,
            folder_dest,
            receipt_folder_name,
        ]
    )

    sharepoint.ctx.web.folders.add(target_folder_url).execute_query()

    logger.info(f"Folder '{folder_dest}' created in SharePoint.")

    local_folder_path = os.path.join(config.PATH, receipt_folder_name)

    if os.path.exists(local_folder_path):
        for file_name in os.listdir(local_folder_path):
            file_full_path = os.path.join(local_folder_path, file_name)

            if os.path.isfile(file_full_path):
                sharepoint.upload_file(folder_name=f"{config.FOLDER_NAME}/Fejlet/{receipt_folder_name}", file_path=file_full_path, file_name=file_name)

    logger.info(f"Folder '{local_folder_path}' and its contents have been uploaded successfully to SharePoint.")


def delete_file_from_sharepoint(file_name: str, sharepoint: Sharepoint) -> None:
    """Delete a file from SharePoint."""

    target_file_url = "/".join(
        [
            # "teams",
            # config.SHAREPOINT_SITE_NAME,
            config.DOCUMENT_LIBRARY,
            config.FOLDER_NAME,
            file_name,
        ]
    )

    try:
        file = sharepoint.ctx.web.get_file_by_server_relative_url(target_file_url)

        file.delete_object()

        sharepoint.ctx.execute_query()

        logger.info(f"File '{file_name}' has been deleted successfully from SharePoint.")

    except Exception as e:
        logger.info(f"Error deleting file '{file_name}': {e}")
