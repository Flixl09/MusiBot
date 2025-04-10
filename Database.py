from enum import Enum
from typing import Type, TypeVar, List
from sqlalchemy import create_engine, MetaData, Column, String, Double, Integer, ForeignKey, TIMESTAMP, Table
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session, declarative_base, relationship
from sqlalchemy.sql.functions import current_timestamp

Base = declarative_base()

songs_playlists = Table(
    "PlaylistSongs", Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("playlist", Integer, ForeignKey("Playlist.id")),
    Column("song", Integer, ForeignKey("Songs.id"))
)

class Artist(Base):
    __tablename__ = 'Artists'
    name = Column(String, unique=True, primary_key=True)

    songs = relationship("Song", back_populates="artists")

class Song(Base):
    __tablename__ = 'Songs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    artist = Column(Integer, ForeignKey('Artists.name'))
    stream_url = Column(String)
    url = Column(String)
    duration = Column(Double)
    platform = Column(Integer, ForeignKey('Platforms.id'))

    platforms = relationship("Platform", back_populates="songs")
    artists = relationship("Artist", back_populates="songs")
    playlist = relationship("Playlist", secondary=songs_playlists, back_populates="songs")
    songstats = relationship("Songstats", back_populates="songs", uselist=False)


class Platform(Base):
    __tablename__ = 'Platforms'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    url = Column(String)

    songs = relationship("Song", back_populates="platforms")

class Songstats(Base):
    __tablename__ = 'Songstats'
    id = Column(Integer, primary_key=True, autoincrement=True)
    song_id = Column(Integer, ForeignKey('Songs.id'))
    play_count = Column(Integer, default=0)
    last_played = Column(TIMESTAMP, default=current_timestamp)

    songs = relationship("Song", back_populates="songstats")

class Playlist(Base):
    __tablename__ = 'Playlist'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    songs = relationship("Song", secondary=songs_playlists, back_populates="playlist")

T = TypeVar("T", bound=Base)

class Database:
    def __init__(self):
        self.engine = create_engine("sqlite:///musiDB.sb", echo=True)
        self.base = Base
        self.session = Session(self.engine)

    def get_all(self, table: Type[T]) -> List[T]:
        return self.session.query(table).all()

    def get_by_id(self, table: Type[T], id: int) -> T:
        if not hasattr(table, 'id'):
            raise ValueError(f"Table {table.__tablename__} does not have an 'id' column.")
        return self.session.query(table).filter(table.id == id).first()

    def get_bulk_by_id(self, table: Type[T], id: List[int]) -> List[T]:
        if not hasattr(table, 'id'):
            raise ValueError(f"Table {table.__tablename__} does not have an 'id' column.")
        return self.session.query(table).filter(table.id.in_(id)).all()

    def get_by_name(self, table: Type[T], name: str) -> T:
        if not hasattr(table, 'name'):
            raise ValueError(f"Table {table.__tablename__} does not have a 'name' column.")

        search_term = f"%{name.replace(' ', '').lower()}%"

        from sqlalchemy import func
        return (
            self.session.query(table)
            .filter(func.replace(func.lower(table.name), ' ', '').like(search_term))
            .first()
        )

    def get_bulk_by_name(self, table: Type[T], name: List[str]) -> List[T]:
        if not hasattr(table, 'name'):
            raise ValueError(f"Table {table.__tablename__} does not have a 'name' column.")
        return self.session.query(table).filter(table.name.in_(name)).all()

    def get_by_url(self, table: Type[T], url: str) -> T:
        if not hasattr(table, 'url'):
            raise ValueError(f"Table {table.__tablename__} does not have a 'url' column.")
        return self.session.query(table).filter(table.url == url).first()

    def get_bulk_by_url(self, table: Type[T], url: List[str]) -> List[T]:
        if not hasattr(table, 'url'):
            raise ValueError(f"Table {table.__tablename__} does not have a 'url' column.")
        return self.session.query(table).filter(table.url.in_(url)).all()

    def get_or_add_by_name(self, table: Type[T], name: str) -> T:
        obj = self.get_by_name(table, name)
        if obj is None:
            obj = table(name=name)
            self.session.add(obj)
            self.session.commit()
        return obj

    def add(self, table: Type[T], obj: T) -> bool:
        if not isinstance(obj, table):
            raise ValueError(f"Object must be an instance of {table.__name__}.")
        self.session.add(obj)
        self.session.commit()
        return True

    def add_bulk(self, table: Type[T], obj: List[T]) -> bool:
        if not all(isinstance(o, table) for o in obj):
            raise ValueError(f"All objects must be instances of {table.__name__}.")
        self.session.add_all(obj)
        self.session.commit()
        return True

    def update(self, table: Type[T], obj: T) -> bool:
        if not isinstance(obj, table):
            raise ValueError(f"Object must be an instance of {table.__name__}.")
        self.session.merge(obj)
        self.session.commit()
        return True

    def delete(self, table: Type[T], obj: T) -> bool:
        if not isinstance(obj, table):
            raise ValueError(f"Object must be an instance of {table.__name__}.")
        self.session.delete(obj)
        self.session.commit()
        return True

    def delete_bulk(self, table: Type[T], obj: List[T]) -> bool:
        if not all(isinstance(o, table) for o in obj):
            raise ValueError(f"All objects must be instances of {table.__name__}.")
        for o in obj:
            self.session.delete(o)
        self.session.commit()
        return True

    def get_dummy(self, table: Type[T]) -> T:
        if table is Artist or table is Song:
            return self.session.query(table).first()
        else:
            raise ValueError(f"Table {table.__tablename__} is not a valid table for this operation.")