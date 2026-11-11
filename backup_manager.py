"""
Backup & Recovery Manager cho Google Sheets
"""

import os
import json
import gzip
import shutil
import io
import hashlib
import secrets
import zipfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import gspread
from google.oauth2.service_account import Credentials
import logging
from reliability import serialized, local_now


class BackupManager:
    """Quản lý backup cho Google Sheets"""
    
    def __init__(
        self,
        gsheet_id: str,
        gsvc_json: str,
        backup_dir: str = "backups"
    ):
        self.gsheet_id = gsheet_id
        self.gsvc_json = gsvc_json
        self.backup_dir = backup_dir
        
        # Create backup directory
        os.makedirs(backup_dir, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Initialize Google Sheets client
        self._init_gsheet()
    
    def _init_gsheet(self):
        """Initialize Google Sheets client"""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
        # Kiểm tra xem có biến môi trường không
        json_content = os.getenv("GOOGLE_JSON_CONTENT")
        
        if json_content:
            # Nạp từ environment variable
            json_info = json.loads(json_content)
            creds = Credentials.from_service_account_info(json_info, scopes=scopes)
        else:
            # Nạp từ file
            creds = Credentials.from_service_account_file(self.gsvc_json, scopes=scopes)
        
        self.gs_client = gspread.authorize(creds)
        self.credentials = creds
        self.gs_sheet = self.gs_client.open_by_key(self.gsheet_id)
    
    def backup_sheet(self, sheet_name: str, compress: bool = True) -> str:
        """
        Backup một sheet cụ thể
        
        Returns:
            Path to backup file
        """
        try:
            worksheet = self.gs_sheet.worksheet(sheet_name)
            data = worksheet.get_all_values()
            
            # Create backup filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{sheet_name}_{timestamp}.json"
            
            if compress:
                filename += ".gz"
            
            filepath = os.path.join(self.backup_dir, filename)
            
            # Save data
            backup_data = {
                "sheet_name": sheet_name,
                "timestamp": timestamp,
                "row_count": len(data),
                "data": data
            }
            
            if compress:
                with gzip.open(filepath, 'wt', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"Backed up {sheet_name} to {filepath}")
            return filepath
            
        except Exception as e:
            self.logger.error(f"Failed to backup {sheet_name}: {e}")
            raise
    
    @serialized
    def backup_all_sheets(self, compress: bool = True) -> List[str]:
        """
        Backup tất cả sheets
        
        Returns:
            List of backup file paths
        """
        worksheets = self.gs_sheet.worksheets()
        backup_files = []
        
        for ws in worksheets:
            try:
                filepath = self.backup_sheet(ws.title, compress=compress)
                backup_files.append(filepath)
            except Exception as e:
                self.logger.error(f"Failed to backup {ws.title}: {e}")
                # A partial backup must not be reported as successful.
                raise
        
        self.logger.info(f"Backed up {len(backup_files)} sheets")
        return backup_files

    def upload_verified_archive(self, files: List[str], folder_id: str) -> Dict[str, str]:
        """Upload to the configured Drive folder and verify downloaded archive bytes.

        Uses existing service-account access; does not create/change sharing permissions.
        Remote copies are never deleted automatically.
        """
        from google.auth.transport.requests import AuthorizedSession

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                # Validate each backup can be read before uploading it.
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    record = json.load(stream)
                if not isinstance(record.get("data"), list) or not record.get("sheet_name"):
                    raise ValueError("Backup file failed validation")
                bundle.write(path, os.path.basename(path))
        content = archive.getvalue()
        now = local_now()
        name = "vm-store-backup-" + now.strftime("%Y%m%d-%H%M%S") + ".zip"
        slots_file = Path(__file__).with_name("backup_slots.json")
        slots = json.loads(slots_file.read_text(encoding="utf-8")) if slots_file.exists() else {}
        file_ids = slots.get("file_ids", []) if slots.get("folder_id") == folder_id else []
        target_id = file_ids[now.date().toordinal() % len(file_ids)] if file_ids else None
        metadata = json.dumps({"name": name, **({} if target_id else {"parents": [folder_id]})})
        boundary = secrets.token_hex(16)
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
                f"--{boundary}\r\nContent-Type: application/zip\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        with AuthorizedSession(self.credentials) as session:
            if target_id:
                target = session.get(f"https://www.googleapis.com/drive/v3/files/{target_id}",
                                     params={"fields": "name,parents,mimeType,capabilities(canEdit)", "supportsAllDrives": "true"}, timeout=30)
                target.raise_for_status()
                details = target.json()
                # Drive may omit parents for non-owner access. These IDs were created and
                # verified in the approved folder; still reject a visible conflicting parent.
                if ((details.get("parents") and folder_id not in details["parents"])
                        or not details.get("name", "").startswith("vm-store-backup-")
                        or not details.get("capabilities", {}).get("canEdit")):
                    raise RuntimeError("Configured backup slot is not editable in the approved folder")
            request = session.patch if target_id else session.post
            url = "https://www.googleapis.com/upload/drive/v3/files" + (f"/{target_id}" if target_id else "")
            response = request(url,
                                    params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,name"},
                                    headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                                    data=body, timeout=120)
            if not response.ok:
                raise RuntimeError(f"Drive backup upload failed (HTTP {response.status_code}); check folder access and storage quota")
            result = response.json()
            check = session.get(f"https://www.googleapis.com/drive/v3/files/{result['id']}",
                                params={"alt": "media", "supportsAllDrives": "true"}, timeout=120)
            check.raise_for_status()
            if hashlib.sha256(content).digest() != hashlib.sha256(check.content).digest():
                raise RuntimeError("Uploaded backup checksum verification failed")
        return {"id": result["id"], "name": name, "sha256": hashlib.sha256(content).hexdigest()}
    
    def restore_sheet(self, backup_file: str, sheet_name: Optional[str] = None):
        """
        Restore sheet từ backup file
        
        Args:
            backup_file: Path to backup file
            sheet_name: Target sheet name (nếu None, dùng tên trong backup)
        """
        try:
            # Load backup data
            if backup_file.endswith('.gz'):
                with gzip.open(backup_file, 'rt', encoding='utf-8') as f:
                    backup_data = json.load(f)
            else:
                with open(backup_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
            
            target_sheet = sheet_name or backup_data['sheet_name']
            data = backup_data['data']
            
            # Get or create worksheet
            try:
                worksheet = self.gs_sheet.worksheet(target_sheet)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = self.gs_sheet.add_worksheet(
                    title=target_sheet,
                    rows=len(data),
                    cols=len(data[0]) if data else 10
                )
            
            # Clear existing data
            worksheet.clear()
            
            # Restore data
            if data:
                worksheet.update(data, value_input_option='RAW')
            
            self.logger.info(f"Restored {target_sheet} from {backup_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to restore from {backup_file}: {e}")
            raise
    
    def list_backups(self, sheet_name: Optional[str] = None) -> List[Dict]:
        """
        List tất cả backup files
        
        Args:
            sheet_name: Filter by sheet name (optional)
        
        Returns:
            List of backup info dicts
        """
        backups = []
        
        for filename in os.listdir(self.backup_dir):
            if not filename.endswith(('.json', '.json.gz')):
                continue
            
            # Parse filename
            parts = filename.replace('.json.gz', '').replace('.json', '').split('_')
            if len(parts) < 3:
                continue
            
            backup_sheet_name = '_'.join(parts[:-2])
            timestamp_str = f"{parts[-2]}_{parts[-1]}"
            
            # Filter by sheet name if specified
            if sheet_name and backup_sheet_name != sheet_name:
                continue
            
            filepath = os.path.join(self.backup_dir, filename)
            file_size = os.path.getsize(filepath)
            
            backups.append({
                'filename': filename,
                'filepath': filepath,
                'sheet_name': backup_sheet_name,
                'timestamp': timestamp_str,
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2)
            })
        
        # Sort by timestamp descending
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return backups
    
    def cleanup_old_backups(self, days: int = 30, keep_minimum: int = 5):
        """
        Xóa backup cũ
        
        Args:
            days: Xóa backup cũ hơn X ngày
            keep_minimum: Giữ lại ít nhất X backup gần nhất cho mỗi sheet
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # Group backups by sheet
        backups_by_sheet = {}
        for backup in self.list_backups():
            sheet = backup['sheet_name']
            if sheet not in backups_by_sheet:
                backups_by_sheet[sheet] = []
            backups_by_sheet[sheet].append(backup)
        
        deleted_count = 0
        
        for sheet, backups in backups_by_sheet.items():
            # Sort by timestamp descending
            backups.sort(key=lambda x: x['timestamp'], reverse=True)
            
            # Keep minimum recent backups
            keep_backups = backups[:keep_minimum]
            check_backups = backups[keep_minimum:]
            
            for backup in check_backups:
                # Parse timestamp
                try:
                    backup_date = datetime.strptime(
                        backup['timestamp'],
                        "%Y%m%d_%H%M%S"
                    )
                    
                    if backup_date < cutoff_date:
                        os.remove(backup['filepath'])
                        deleted_count += 1
                        self.logger.info(f"Deleted old backup: {backup['filename']}")
                        
                except Exception as e:
                    self.logger.error(f"Failed to delete {backup['filename']}: {e}")
        
        self.logger.info(f"Cleaned up {deleted_count} old backups")
        return deleted_count
    
    def export_to_csv(self, sheet_name: str, output_file: str):
        """Export sheet to CSV"""
        import csv
        
        try:
            worksheet = self.gs_sheet.worksheet(sheet_name)
            data = worksheet.get_all_values()
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(data)
            
            self.logger.info(f"Exported {sheet_name} to {output_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to export {sheet_name}: {e}")
            raise
    
    def import_from_csv(self, csv_file: str, sheet_name: str):
        """Import CSV to sheet"""
        import csv
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                data = list(reader)
            
            # Get or create worksheet
            try:
                worksheet = self.gs_sheet.worksheet(sheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = self.gs_sheet.add_worksheet(
                    title=sheet_name,
                    rows=len(data),
                    cols=len(data[0]) if data else 10
                )
            
            # Clear and update
            worksheet.clear()
            if data:
                worksheet.update(data, value_input_option='RAW')
            
            self.logger.info(f"Imported {csv_file} to {sheet_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to import {csv_file}: {e}")
            raise
    
    def create_snapshot(self) -> str:
        """
        Tạo snapshot của toàn bộ spreadsheet
        
        Returns:
            Path to snapshot file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_file = os.path.join(
            self.backup_dir,
            f"snapshot_{timestamp}.json.gz"
        )
        
        # Backup all sheets
        all_data = {}
        for ws in self.gs_sheet.worksheets():
            all_data[ws.title] = ws.get_all_values()
        
        snapshot_data = {
            "timestamp": timestamp,
            "spreadsheet_id": self.gsheet_id,
            "spreadsheet_title": self.gs_sheet.title,
            "sheets": all_data
        }
        
        with gzip.open(snapshot_file, 'wt', encoding='utf-8') as f:
            json.dump(snapshot_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"Created snapshot: {snapshot_file}")
        return snapshot_file
    
    def restore_snapshot(self, snapshot_file: str):
        """Restore từ snapshot"""
        try:
            with gzip.open(snapshot_file, 'rt', encoding='utf-8') as f:
                snapshot_data = json.load(f)
            
            for sheet_name, data in snapshot_data['sheets'].items():
                try:
                    worksheet = self.gs_sheet.worksheet(sheet_name)
                except gspread.exceptions.WorksheetNotFound:
                    worksheet = self.gs_sheet.add_worksheet(
                        title=sheet_name,
                        rows=len(data),
                        cols=len(data[0]) if data else 10
                    )
                
                worksheet.clear()
                if data:
                    worksheet.update(data, value_input_option='RAW')
            
            self.logger.info(f"Restored snapshot from {snapshot_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to restore snapshot: {e}")
            raise


# ============= USAGE EXAMPLES =============

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize
    backup_manager = BackupManager(
        gsheet_id=os.getenv("GSHEET_ID"),
        gsvc_json=os.getenv("GSVC_JSON", "service_account.json")
    )
    
    # 1. Backup single sheet
    backup_manager.backup_sheet("ORDERS")
    
    # 2. Backup all sheets
    backup_manager.backup_all_sheets()
    
    # 3. List backups
    backups = backup_manager.list_backups()
    for backup in backups:
        print(f"{backup['filename']} - {backup['size_mb']} MB")
    
    # 4. Restore from backup
    # backup_manager.restore_sheet("ORDERS_20260510_120000.json.gz")
    
    # 5. Create snapshot
    backup_manager.create_snapshot()
    
    # 6. Cleanup old backups
    backup_manager.cleanup_old_backups(days=30, keep_minimum=5)
    
    # 7. Export to CSV
    backup_manager.export_to_csv("ORDERS", "orders_export.csv")
