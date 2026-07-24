from sqlalchemy import Column, ForeignKey, Integer, String, JSON
from ..db import Base


class EVSEntry(Base):
    """
    一个EVS文件对应一个HGAR内部的文件
    一个EVS文件对应多条EVSEntry
    """
    __tablename__ = "evs_entries"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Integer)
    # Calculated at runtime
    # size = Column(Integer)
    param = Column(JSON)
    sentence_key = Column(String, ForeignKey("sentences.key"), nullable=True)

    hgar_file_id = Column(
        Integer, ForeignKey("hgar_files.id"), index=True, nullable=False
    )

    def __repr__(self):
        return f"<EVSEntry(id = {self.id} type='{self.type}'),param='{self.param}'>\n"
