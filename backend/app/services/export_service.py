class ExportService:
    def export(self, project_id: int, format: str = "mp4"):
        return {"url": f"/exports/{project_id}.{format}"}
