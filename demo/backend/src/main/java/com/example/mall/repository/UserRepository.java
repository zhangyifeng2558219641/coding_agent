package com.example.mall.repository;

import com.example.mall.entity.User;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.util.List;

/**
 * 用户数据访问(H2 + JdbcTemplate)
 */
@Repository
public class UserRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public UserRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<User> ROW_MAPPER = (rs, i) -> {
        User u = new User();
        u.setId(rs.getLong("id"));
        u.setUsername(rs.getString("username"));
        u.setPasswordHash(rs.getString("password_hash"));
        u.setNickname(rs.getString("nickname"));
        u.setEmail(rs.getString("email"));
        u.setPhone(rs.getString("phone"));
        u.setRole(rs.getString("role"));
        u.setPoints(rs.getInt("points"));
        u.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
        return u;
    };

    public Long insert(User user) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO app_user (username, password_hash, nickname, email, phone, role, points) " +
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    new String[]{"id"});
            ps.setString(1, user.getUsername());
            ps.setString(2, user.getPasswordHash());
            ps.setString(3, user.getNickname());
            ps.setString(4, user.getEmail());
            ps.setString(5, user.getPhone());
            ps.setString(6, user.getRole());
            ps.setInt(7, user.getPoints());
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? null : key.longValue();
    }

    public User findById(Long id) {
        List<User> list = jdbc.query("SELECT * FROM app_user WHERE id = ?", ROW_MAPPER, id);
        return list.isEmpty() ? null : list.get(0);
    }

    public User findByEmail(String email) {
        List<User> list = jdbc.query("SELECT * FROM app_user WHERE email = ?", ROW_MAPPER, email);
        return list.isEmpty() ? null : list.get(0);
    }

    public List<User> listAll() {
        return jdbc.query("SELECT * FROM app_user ORDER BY id", ROW_MAPPER);
    }

    public int count() {
        Integer c = jdbc.queryForObject("SELECT COUNT(*) FROM app_user", Integer.class);
        return c == null ? 0 : c;
    }

    /** 更新积分(用于管理员调整/消费/获得积分) */
    public int updatePoints(Long id, int newPoints) {
        return jdbc.update("UPDATE app_user SET points = ? WHERE id = ?", newPoints, id);
    }

    /** 更新昵称与手机号 */
    public int updateProfile(Long id, String nickname, String phone) {
        return jdbc.update("UPDATE app_user SET nickname = ?, phone = ? WHERE id = ?", nickname, phone, id);
    }

    /** 更新密码哈希 */
    public int updatePassword(Long id, String passwordHash) {
        return jdbc.update("UPDATE app_user SET password_hash = ? WHERE id = ?", passwordHash, id);
    }
}
