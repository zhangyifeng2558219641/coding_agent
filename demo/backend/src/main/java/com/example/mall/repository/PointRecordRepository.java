package com.example.mall.repository;

import com.example.mall.entity.PointRecord;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.util.List;

/**
 * 积分流水数据访问(H2 + JdbcTemplate)
 */
@Repository
public class PointRecordRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public PointRecordRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<PointRecord> ROW_MAPPER = (rs, i) -> {
        PointRecord r = new PointRecord();
        r.setId(rs.getLong("id"));
        r.setUserId(rs.getLong("user_id"));
        r.setType(rs.getString("type"));
        r.setPoints(rs.getInt("points"));
        r.setBalance(rs.getInt("balance"));
        r.setOrderId(rs.getObject("order_id") == null ? null : rs.getLong("order_id"));
        r.setRemark(rs.getString("remark"));
        r.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
        return r;
    };

    public Long insert(String type, int points, int balance, Long orderId, String remark, Long userId) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO point_record (user_id, type, points, balance, order_id, remark) VALUES (?, ?, ?, ?, ?, ?)",
                    new String[]{"id"});
            ps.setLong(1, userId);
            ps.setString(2, type);
            ps.setInt(3, points);
            ps.setInt(4, balance);
            if (orderId == null) {
                ps.setNull(5, java.sql.Types.BIGINT);
            } else {
                ps.setLong(5, orderId);
            }
            ps.setString(6, remark);
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? null : key.longValue();
    }

    public List<PointRecord> listByUser(Long userId) {
        return jdbc.query("SELECT * FROM point_record WHERE user_id = ? ORDER BY id DESC", ROW_MAPPER, userId);
    }
}
